# core/urls.py

from django.urls import path
from . import views
urlpatterns = [
    # --- Autenticación y Dashboards ---
    path('', views.UserLoginView.as_view(), name='login'),
    path('logout/', views.UserLogoutView.as_view(), name='logout'),
    path('dashboard/', views.dashboard_redirect, name='dashboard'),
    path('dashboard/admin/', views.dashboard_admin, name='dashboard_admin'),
    path('dashboard/mesero/', views.dashboard_mesero, name='dashboard_mesero'),
    path('dashboard/cocinero/', views.dashboard_cocinero, name='dashboard_cocinero'),
    path('dashboard/cajero/', views.dashboard_cajero, name='dashboard_cajero'),
    path('acceso-denegado/', views.acceso_denegado_view, name='acceso_denegado'),

    # --- API para CRUD de Productos ---
    path('api/productos/', views.api_productos_list_create, name='api_productos_list_create'),
    path('api/productos/<int:pk>/', views.api_producto_detail, name='api_producto_detail'),

    # --- API para Lógica de Negocio ---
    path('api/orden/crear/', views.api_crear_orden, name='api_crear_orden'),
    
    # --- APIS PARA LA COCINA (LAS QUE FALTABAN) ---
    path('api/cocina/ordenes/', views.api_get_ordenes_cocina, name='api_get_ordenes_cocina'),
    path('api/cocina/producto/<int:producto_orden_id>/listo/', views.api_marcar_producto_listo, name='api_marcar_producto_listo'),
]