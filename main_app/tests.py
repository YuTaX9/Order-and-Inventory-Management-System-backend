from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock
from .models import Category, Product, Order, OrderItem, ShippingZone
from .serializers import ProductSerializer, OrderSerializer


# ============================================
# 1. Model Tests
# ============================================

class CategoryModelTest(TestCase):
    """Tests for Category model"""
    
    def setUp(self):
        self.category = Category.objects.create(
            name='Electronics',
            description='Electronic products'
        )
    
    def test_category_creation(self):
        """Test creating a category"""
        self.assertEqual(self.category.name, 'Electronics')
        self.assertEqual(str(self.category), 'Electronics')
        self.assertIsNotNone(self.category.created_at)
    
    def test_category_unique_name(self):
        """Test that category names must be unique"""
        with self.assertRaises(Exception):
            Category.objects.create(name='Electronics')
    
    def test_category_ordering(self):
        """Test categories are ordered by name"""
        Category.objects.create(name='Books')
        Category.objects.create(name='Clothing')
        categories = list(Category.objects.all())
        self.assertEqual(categories[0].name, 'Books')
        self.assertEqual(categories[1].name, 'Clothing')


class ProductModelTest(TestCase):
    """Tests for Product model"""
    
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass123'
        )
        self.category = Category.objects.create(name='Electronics')
        self.product = Product.objects.create(
            user=self.user,
            category=self.category,
            name='Laptop',
            description='Gaming laptop',
            price=Decimal('999.99'),
            stock_quantity=50,
            sku='LAP001',
            is_active=True
        )
    
    def test_product_creation(self):
        """Test creating a product"""
        self.assertEqual(self.product.name, 'Laptop')
        self.assertEqual(self.product.price, Decimal('999.99'))
        self.assertEqual(self.product.stock_quantity, 50)
        self.assertTrue(self.product.is_active)
    
    def test_product_str(self):
        """Test product string representation"""
        self.assertEqual(str(self.product), 'Laptop (SKU: LAP001)')
    
    def test_is_in_stock_property(self):
        """Test is_in_stock property"""
        self.assertTrue(self.product.is_in_stock)
        
        self.product.stock_quantity = 0
        self.product.save()
        self.assertFalse(self.product.is_in_stock)
    
    def test_is_low_stock_property(self):
        """Test is_low_stock property"""
        self.product.stock_quantity = 5
        self.product.save()
        self.assertTrue(self.product.is_low_stock)
        
        self.product.stock_quantity = 15
        self.product.save()
        self.assertFalse(self.product.is_low_stock)
        
        self.product.stock_quantity = 0
        self.product.save()
        self.assertFalse(self.product.is_low_stock)
    
    def test_unique_sku(self):
        """Test that SKU must be unique"""
        with self.assertRaises(Exception):
            Product.objects.create(
                user=self.user,
                category=self.category,
                name='Another Laptop',
                description='Test',
                price=Decimal('500.00'),
                stock_quantity=10,
                sku='LAP001'  # Same SKU
            )
    
    def test_price_validation(self):
        """Test that price cannot be negative"""
        from django.core.exceptions import ValidationError
        product = Product(
            user=self.user,
            name='Test Product',
            description='Test',
            price=Decimal('-10.00'),
            stock_quantity=10,
            sku='TEST001'
        )
        with self.assertRaises(ValidationError):
            product.full_clean()
