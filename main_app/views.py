from rest_framework import generics, viewsets, filters, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.permissions import IsAdminUser
from django.db.models import Sum, Count, Q
from django.contrib.auth.models import User
from django_filters.rest_framework import DjangoFilterBackend
from .models import Category, Product, Order, OrderItem
from .serializers import RegisterSerializer, UserSerializer, CategorySerializer, ProductSerializer, OrderSerializer, OrderCreateSerializer, OrderItemSerializer
from .permissions import IsOwnerOrAdmin

class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = (AllowAny,)
    serializer_class = RegisterSerializer

class ProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = (IsAuthenticated,)
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [permissions.IsAdminUser()]
        return [permissions.AllowAny()]
    
    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        category = self.get_object()
        products = category.products.filter(is_active=True)
        serializer = ProductSerializer(products, many=True)
        return Response(serializer.data)

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrAdmin]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'is_active']
    search_fields = ['name', 'description', 'sku']
    ordering_fields = ['price', 'created_at', 'stock_quantity']
    ordering = ['-created_at']
    
    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Filter by price range
        min_price = self.request.query_params.get('min_price')
        max_price = self.request.query_params.get('max_price')
        
        if min_price:
            queryset = queryset.filter(price__gte=min_price)
        if max_price:
            queryset = queryset.filter(price__lte=max_price)
        
        # Filter by stock availability
        in_stock = self.request.query_params.get('in_stock')
        if in_stock == 'true':
            queryset = queryset.filter(stock_quantity__gt=0)
        
        return queryset
    
    @action(detail=False, methods=['get'], permission_classes=[permissions.IsAdminUser])
    def low_stock(self, request):
        products = Product.objects.filter(stock_quantity__lt=10, stock_quantity__gt=0, is_active=True)
        serializer = self.get_serializer(products, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['patch'], permission_classes=[permissions.IsAuthenticated, IsOwnerOrAdmin])
    def update_stock(self, request, pk=None):
        product = self.get_object()
        new_quantity = request.data.get('stock_quantity')
        
        if new_quantity is None:
            return Response({'error': 'stock_quantity is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            new_quantity = int(new_quantity)
            if new_quantity < 0:
                return Response({'error': 'Stock quantity cannot be negative'}, status=status.HTTP_400_BAD_REQUEST)
            
            product.stock_quantity = new_quantity
            product.save()
            serializer = self.get_serializer(product)
            return Response(serializer.data)
        except ValueError:
            return Response({'error': 'Invalid stock quantity'}, status=status.HTTP_400_BAD_REQUEST)

class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_staff:
            # Admin sees all orders
            queryset = Order.objects.all()
        else:
            # Regular users see only their orders
            queryset = Order.objects.filter(user=user)
        
        # Filter by status
        status = self.request.query_params.get('status')
        if status:
            queryset = queryset.filter(status=status)
        
        return queryset.order_by('-order_date')
    
    def get_serializer_class(self):
        if self.action == 'create':
            return OrderCreateSerializer
        return OrderSerializer
    
    @action(detail=False, methods=['get'])
    def my_orders(self, request):
        """Get current user's orders"""
        orders = Order.objects.filter(user=request.user)

        status = request.query_params.get('status')
        if status:
            orders = orders.filter(status=status)

        orders = orders.order_by('-order_date')
        serializer = self.get_serializer(orders, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an order and restore stock"""
        order = self.get_object()
        
        # Check if user owns the order or is admin
        if order.user != request.user and not request.user.is_staff:
            return Response(
                {'error': 'You do not have permission to cancel this order'},
                status=status.HTTP_403_FORBIDDEN
            )

        if not order.can_be_cancelled:
            return Response(
                {'error': 'This order cannot be cancelled'},
                status=status.HTTP_400_BAD_REQUEST
            )

        for item in order.order_items.all():
            product = item.product
            product.stock_quantity += item.quantity
            product.save()
        
        # Update order status
        order.status = 'cancelled'
        order.save()
        
        serializer = self.get_serializer(order)
        return Response(serializer.data)
    
    @action(detail=True, methods=['patch'], permission_classes=[permissions.IsAdminUser])
    def update_status(self, request, pk=None):
        """Update order status (Admin only)"""
        order = self.get_object()
        new_status = request.data.get('status')
        
        if not new_status:
            return Response(
                {'error': 'Status is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        valid_statuses = ['pending', 'processing', 'shipped', 'delivered', 'cancelled']
        if new_status not in valid_statuses:
            return Response(
                {'error': f'Invalid status. Must be one of: {", ".join(valid_statuses)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Cannot change from delivered or cancelled
        if order.status in ['delivered', 'cancelled']:
            return Response(
                {'error': 'Cannot change status of delivered or cancelled orders'},
                status=status.HTTP_400_BAD_REQUEST
            )

        order.status = new_status
        order.save()

        serializer = self.get_serializer(order)
        return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAdminUser])
def admin_stats(request):
    """Get dashboard statistics for admin"""
    
    # Total products
    total_products = Product.objects.filter(is_active=True).count()
    
    # Low stock products
    low_stock_count = Product.objects.filter(
        stock_quantity__lt=10, 
        stock_quantity__gt=0,
        is_active=True
    ).count()
    
    # Out of stock products
    out_of_stock_count = Product.objects.filter(
        stock_quantity=0,
        is_active=True
    ).count()
    
    # Total orders
    total_orders = Order.objects.count()
    
    # Orders by status
    orders_by_status = {
        'pending': Order.objects.filter(status='pending').count(),
        'processing': Order.objects.filter(status='processing').count(),
        'shipped': Order.objects.filter(status='shipped').count(),
        'delivered': Order.objects.filter(status='delivered').count(),
        'cancelled': Order.objects.filter(status='cancelled').count(),
    }
    
    # Total revenue (from delivered orders)
    total_revenue = Order.objects.filter(
        status='delivered'
    ).aggregate(total=Sum('total_amount'))['total'] or 0
    
    # Recent orders (last 10)
    recent_orders = Order.objects.all().order_by('-order_date')[:10]
    recent_orders_data = OrderSerializer(recent_orders, many=True).data
    
    return Response({
        'total_products': total_products,
        'low_stock_count': low_stock_count,
        'out_of_stock_count': out_of_stock_count,
        'total_orders': total_orders,
        'orders_by_status': orders_by_status,
        'total_revenue': float(total_revenue),
        'recent_orders': recent_orders_data
    })