from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from .models import Category, Product, Order, OrderItem

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'password2')

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Passwords don't match"})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password2')
        user = User.objects.create_user(**validated_data)
        return user

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email')

class CategorySerializer(serializers.ModelSerializer):
    products_count = serializers.SerializerMethodField()
    
    class Meta:
        model = Category
        fields = ['id', 'name', 'description', 'products_count', 'created_at']
    
    def get_products_count(self, obj):
        return obj.products.filter(is_active=True).count()

class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    is_in_stock = serializers.BooleanField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Product
        fields = [
            'id', 'user', 'user_username', 'category', 'category_name',
            'name', 'description', 'price', 'stock_quantity', 'sku',
            'image_url', 'is_active', 'is_in_stock', 'is_low_stock',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['user', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)
    
class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_image = serializers.CharField(source='product.image_url', read_only=True)
    
    class Meta:
        model = OrderItem
        fields = [
            'id', 'product', 'product_name', 'product_image',
            'quantity', 'unit_price', 'subtotal', 'created_at'
        ]
        read_only_fields = ['subtotal', 'created_at']

class OrderSerializer(serializers.ModelSerializer):
    order_items = OrderItemSerializer(many=True, read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    can_be_cancelled = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Order
        fields = [
            'id', 'user', 'user_username', 'order_number',
            'total_amount', 'status', 'shipping_address', 'notes',
            'order_date', 'updated_at', 'order_items', 'can_be_cancelled'
        ]
        read_only_fields = ['user', 'order_number', 'total_amount', 'order_date', 'updated_at']

class OrderCreateSerializer(serializers.ModelSerializer):
    order_items = serializers.ListField(
        child=serializers.DictField(),
        write_only=True
    )
    
    class Meta:
        model = Order
        fields = ['shipping_address', 'notes', 'order_items']
    
    def validate_order_items(self, value):
        if not value or len(value) == 0:
            raise serializers.ValidationError("Order must contain at least one item")
        
        for item in value:
            if 'product_id' not in item or 'quantity' not in item:
                raise serializers.ValidationError("Each item must have product_id and quantity")
            
            if item['quantity'] < 1:
                raise serializers.ValidationError("Quantity must be at least 1")
        
        return value
    
    def create(self, validated_data):
        order_items_data = validated_data.pop('order_items')

        order = Order.objects.create(
            user=self.context['request'].user,
            **validated_data
        )

        for item_data in order_items_data:
            product = Product.objects.get(id=item_data['product_id'])

            if product.stock_quantity < item_data['quantity']:
                order.delete()
                raise serializers.ValidationError(
                    f"Insufficient stock for {product.name}. Available: {product.stock_quantity}"
                )

            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=item_data['quantity'],
                unit_price=product.price
            )

            product.stock_quantity -= item_data['quantity']
            product.save()

        order.calculate_total()

        return order