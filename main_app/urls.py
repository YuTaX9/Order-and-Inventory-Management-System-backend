from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import RegisterView, ProfileView, CategoryViewSet, ProductViewSet, OrderViewSet, ShippingZoneViewSet, admin_stats, request_password_reset, reset_password, calculate_shipping_preview, stripe_config, create_payment_intent, confirm_payment, change_password

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'orders', OrderViewSet, basename='order')
router.register(r'shipping-zones', ShippingZoneViewSet, basename='shipping-zone')

urlpatterns = [
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='login'),
    path('auth/change-password/', change_password, name='change_password'),
    path('auth/password-reset/', request_password_reset, name='password_reset_request'),
    path('auth/password-reset/<uid>/<token>/', reset_password, name='password_reset'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('calculate-shipping/', calculate_shipping_preview, name='calculate_shipping'),
    path('stripe/config/', stripe_config, name='stripe_config'),
    path('stripe/create-payment-intent/', create_payment_intent, name='create_payment_intent'),
    path('stripe/confirm-payment/', confirm_payment, name='confirm_payment'),
    path('auth/profile/', ProfileView.as_view(), name='profile'),
    path('admin/stats/', admin_stats, name='admin_stats'),
    path('', include(router.urls)),
]