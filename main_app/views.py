from decimal import Decimal
from rest_framework import generics, viewsets, filters, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.permissions import IsAdminUser
from django.db.models import Sum, Count, Q
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import send_mail
import stripe
from django.conf import settings
from django_filters.rest_framework import DjangoFilterBackend
from .models import Category, Product, Order, ShippingZone, OrderItem
from .serializers import RegisterSerializer, UserSerializer, CategorySerializer, ProductSerializer, OrderSerializer, OrderCreateSerializer, ShippingZoneSerializer, OrderItemSerializer
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

        min_price = self.request.query_params.get('min_price')
        max_price = self.request.query_params.get('max_price')
        
        if min_price:
            queryset = queryset.filter(price__gte=min_price)
        if max_price:
            queryset = queryset.filter(price__lte=max_price)

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

            queryset = Order.objects.all()
        else:

            queryset = Order.objects.filter(user=user)

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

        if order.status in ['delivered', 'cancelled']:
            return Response(
                {'error': 'Cannot change status of delivered or cancelled orders'},
                status=status.HTTP_400_BAD_REQUEST
            )

        order.status = new_status
        order.save()

        serializer = self.get_serializer(order)
        return Response(serializer.data)
    
class ShippingZoneViewSet(viewsets.ReadOnlyModelViewSet):
    """Get available shipping zones"""
    queryset = ShippingZone.objects.all()
    serializer_class = ShippingZoneSerializer
    permission_classes = [permissions.AllowAny]

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def calculate_shipping_preview(request):
    """Preview shipping cost before placing order"""
    shipping_zone_id = request.data.get('shipping_zone_id')
    cart_total = Decimal(str(request.data.get('cart_total', 0)))
    
    if not shipping_zone_id:
        return Response({'shipping_cost': 0})
    
    try:
        zone = ShippingZone.objects.get(id=shipping_zone_id)

        if zone.free_shipping_threshold and cart_total >= zone.free_shipping_threshold:
            return Response({
                'shipping_cost': 0,
                'is_free': True,
                'message': 'Free shipping!'
            })
        
        return Response({
            'shipping_cost': float(zone.base_rate),
            'is_free': False
        })
        
    except ShippingZone.DoesNotExist:
        return Response({'error': 'Invalid shipping zone'}, status=400)

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

@api_view(['POST'])
@permission_classes([AllowAny])
def request_password_reset(request):
    """Request password reset - sends email with reset link"""
    email = request.data.get('email')
    
    if not email:
        return Response({'error': 'Email is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        user = User.objects.get(email=email)
        
        # Generate token
        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        
        # Create reset link
        reset_link = f"{settings.FRONTEND_URL}/reset-password/{uid}/{token}/"
        
        # Send email (في الإنتاج استخدم Email service حقيقي)
        # في التطوير يمكن طباعة الرابط في console
        print(f"Password Reset Link: {reset_link}")
        
        # TODO: Send actual email
        # send_mail(
        #     'Password Reset Request',
        #     f'Click this link to reset your password: {reset_link}',
        #     settings.DEFAULT_FROM_EMAIL,
        #     [email],
        #     fail_silently=False,
        # )
        
        return Response({
            'message': 'Password reset link sent to your email',
            'reset_link': reset_link  # Remove this in production
        })
        
    except User.DoesNotExist:
        # Don't reveal if email exists
        return Response({
            'message': 'If this email exists, a reset link has been sent'
        })

@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password(request, uidb64, token):
    """Reset password with token"""
    new_password = request.data.get('new_password')
    
    if not new_password:
        return Response({'error': 'New password is required'}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
        
        # Verify token
        if not default_token_generator.check_token(user, token):
            return Response({'error': 'Invalid or expired reset link'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Set new password
        user.set_password(new_password)
        user.save()
        
        return Response({'message': 'Password reset successfully'})
        
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return Response({'error': 'Invalid reset link'}, status=status.HTTP_400_BAD_REQUEST)

stripe.api_key = settings.STRIPE_SECRET_KEY

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def create_payment_intent(request):
    """Create Stripe payment intent"""
    try:
        amount = int(float(request.data.get('amount', 0)) * 100)  # Convert to cents
        order_id = request.data.get('order_id')
        
        if amount <= 0:
            return Response(
                {'error': 'Invalid amount'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create payment intent
        intent = stripe.PaymentIntent.create(
            amount=amount,
            currency='usd',
            metadata={
                'order_id': order_id,
                'user_id': request.user.id
            }
        )
        
        return Response({
            'clientSecret': intent.client_secret,
            'paymentIntentId': intent.id
        })
        
    except Exception as e:
        return Response(
            {'error': str(e)}, 
            status=status.HTTP_400_BAD_REQUEST
        )

@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def confirm_payment(request):
    """Confirm payment and update order"""
    payment_intent_id = request.data.get('payment_intent_id')
    order_id = request.data.get('order_id')
    
    try:
        # Verify payment intent
        intent = stripe.PaymentIntent.retrieve(payment_intent_id)
        
        if intent.status == 'succeeded':
            # Update order
            order = Order.objects.get(id=order_id, user=request.user)
            order.payment_status = 'paid'
            order.payment_intent_id = payment_intent_id
            order.save()
            
            return Response({
                'message': 'Payment confirmed',
                'order': OrderSerializer(order).data
            })
        else:
            return Response(
                {'error': 'Payment not completed'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
            
    except Order.DoesNotExist:
        return Response(
            {'error': 'Order not found'}, 
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        return Response(
            {'error': str(e)}, 
            status=status.HTTP_400_BAD_REQUEST
        )

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def stripe_config(request):
    """Get Stripe publishable key"""
    return Response({
        'publicKey': settings.STRIPE_PUBLISHABLE_KEY
    })