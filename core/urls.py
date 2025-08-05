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
    
    # --- APIs PARA LA COCINA ---
    path('api/cocina/ordenes/', views.api_get_ordenes_cocina, name='api_get_ordenes_cocina'),
    path('api/cocina/producto/<int:producto_orden_id>/listo/', views.api_marcar_producto_listo, name='api_marcar_producto_listo'),
    path('api/cocina/producto/<int:producto_orden_id>/decrementar/', views.api_decrementar_producto, name='api_decrementar_producto'),


    # --- APIs PARA ÓRDENES (TIEMPO REAL) ---
    path('api/orden/crear/', views.api_crear_orden_tiempo_real, name='api_crear_orden'),
    
path('api/cocina/orden/<int:orden_id>/servida/', views.api_marcar_orden_servida, name='api_marcar_orden_servida'),
    # --- APIs PARA LA COCINA (TIEMPO REAL) ---
    path('api/cocina/ordenes/', views.api_get_ordenes_cocina, name='api_get_ordenes_cocina'),
    path('api/cocina/producto/<int:producto_orden_id>/listo/', views.api_marcar_producto_listo_tiempo_real, name='api_marcar_producto_listo'),
    path('api/cocina/producto/<int:producto_orden_id>/decrementar/', views.api_decrementar_producto_tiempo_real, name='api_decrementar_producto'),
    
    # 🚀 LONG POLLING ENDPOINTS
    path('api/longpolling/cocina/', views.api_longpolling_cocina, name='api_longpolling_cocina'),
    path('api/longpolling/meseros/', views.api_longpolling_meseros, name='api_longpolling_meseros'),
    path('api/sistema/estadisticas/', views.api_estadisticas_sistema, name='api_estadisticas_sistema'),


]