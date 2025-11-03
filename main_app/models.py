from django.db import models

# Create your models here.

from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from decimal import Decimal

class Category(models.Model):
    """Product categories for organization"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    """Main product model with inventory tracking"""
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='products'
    )
    category = models.ForeignKey(
        Category, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='products'
    )
    name = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))]
    )
    stock_quantity = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)]
    )
    sku = models.CharField(max_length=50, unique=True)
    image_url = models.URLField(max_length=500, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['sku']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return f"{self.name} (SKU: {self.sku})"

    @property
    def is_in_stock(self):
        """Check if product has available stock"""
        return self.stock_quantity > 0

    @property
    def is_low_stock(self):
        """Check if stock is below threshold"""
        return self.stock_quantity < 10 and self.stock_quantity > 0


class ShippingZone(models.Model):
    """Shipping zones with different rates"""
    name = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    base_rate = models.DecimalField(max_digits=10, decimal_places=2)
    free_shipping_threshold = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        null=True, 
        blank=True,
        help_text="Order total for free shipping"
    )
    
    class Meta:
        ordering = ['name']
    
    def __str__(self):
        return f"{self.name} - {self.country}"

class Order(models.Model):
    """Customer orders"""

    payment_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('paid', 'Paid'),
            ('failed', 'Failed'),
            ('refunded', 'Refunded')
        ],
        default='pending'
    )
    payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='orders'
    )
    order_number = models.CharField(max_length=20, unique=True, editable=False)
    total_amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        default=Decimal('0.00')
    )
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='pending'
    )
    shipping_address = models.TextField()
    notes = models.TextField(blank=True, null=True)
    order_date = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    shipping_zone = models.ForeignKey(
        'ShippingZone',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    shipping_cost = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00')
    )
    
    def calculate_shipping(self):
        """Calculate shipping cost based on zone and order total"""
        if not self.shipping_zone:
            return Decimal('0.00')

        if (self.shipping_zone.free_shipping_threshold and 
            self.total_amount >= self.shipping_zone.free_shipping_threshold):
            return Decimal('0.00')

        total_weight = sum(
            item.product.weight * item.quantity 
            for item in self.order_items.all()
            if hasattr(item.product, 'weight') and item.product.weight
        )
        
        shipping_cost = self.shipping_zone.base_rate
        if total_weight > 0:
            shipping_cost += total_weight * self.shipping_zone.per_kg_rate
        
        return shipping_cost
    
    def get_final_total(self):
        """Get total including shipping"""
        return self.total_amount + self.shipping_cost

    class Meta:
        ordering = ['-order_date']
        indexes = [
            models.Index(fields=['order_number']),
            models.Index(fields=['user', 'status']),
        ]

    def __str__(self):
        return f"Order {self.order_number} - {self.user.username}"

    def save(self, *args, **kwargs):
        """Generate unique order number on creation"""
        if not self.order_number:
            import uuid
            self.order_number = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def calculate_total(self):
        """Calculate total from order items"""
        total = sum(item.subtotal for item in self.order_items.all())
        self.total_amount = total
        self.save()
        return total

    @property
    def can_be_cancelled(self):
        """Check if order can be cancelled"""
        return self.status == 'pending'


class OrderItem(models.Model):
    """Individual items within an order"""
    order = models.ForeignKey(
        Order, 
        on_delete=models.CASCADE, 
        related_name='order_items'
    )
    product = models.ForeignKey(
        Product, 
        on_delete=models.PROTECT,
        related_name='order_items'
    )
    quantity = models.IntegerField(
        validators=[MinValueValidator(1)]
    )
    unit_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2
    )
    subtotal = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        unique_together = ['order', 'product']

    def __str__(self):
        return f"{self.quantity}x {self.product.name} in {self.order.order_number}"

    def save(self, *args, **kwargs):
        """Calculate subtotal before saving"""
        self.subtotal = self.quantity * self.unit_price
        super().save(*args, **kwargs)
        # Update order total after saving
        self.order.calculate_total()

    def delete(self, *args, **kwargs):
        """Update order total after deletion"""
        order = self.order
        super().delete(*args, **kwargs)
        order.calculate_total()