# core/urls.py - URLs CORREGIDAS Y ORGANIZADAS - VERSIÓN FINAL

from django.urls import path
from . import views

urlpatterns = [
    # === AUTENTICACIÓN ===
    path('', views.UserLoginView.as_view(), name='login'),
    path('logout/', views.UserLogoutView.as_view(), name='logout'),
    path('acceso-denegado/', views.acceso_denegado_view, name='acceso_denegado'),

    # === DASHBOARDS PRINCIPALES ===
    path('dashboard/', views.dashboard_redirect, name='dashboard'),
    path('dashboard/admin/', views.dashboard_admin, name='dashboard_admin'),
    path('dashboard/cajero/', views.dashboard_cajero, name='dashboard_cajero'),
    path('dashboard/cocinero/', views.dashboard_cocinero, name='dashboard_cocinero'),
    
    # === DASHBOARDS DE MESERO (SEPARADOS) ===
    path('dashboard/mesero/', views.dashboard_mesero, name='dashboard_mesero'),
    path('mesero/nuevo-pedido/', views.mesero_nuevo_pedido, name='mesero_nuevo_pedido'),
    path('mesero/modificar-orden/', views.mesero_modificar_orden, name='mesero_modificar_orden'),
    path('mesero/vista-cocina/', views.mesero_vista_cocina, name='mesero_vista_cocina'),
    path('mesero/mis-ordenes/', views.mesero_mis_ordenes, name='mesero_mis_ordenes'),

    # === API PRODUCTOS (CRUD BÁSICO) ===
    path('api/productos/', views.api_productos_list_create, name='api_productos_list_create'),
    path('api/productos/<int:pk>/', views.api_producto_detail, name='api_producto_detail'),

    # === API ÓRDENES (CREAR Y GESTIONAR) ===
    path('api/orden/crear/', views.api_crear_orden_tiempo_real, name='api_crear_orden'),
    path('api/orden/<int:orden_id>/agregar-productos/', views.api_agregar_productos_orden, name='api_agregar_productos_orden'),
    # ✅ UBICACIÓN CORRECTA - DENTRO DE LA SECCIÓN DE ÓRDENES
    path('api/orden/<int:orden_id>/agregar-productos-facturada/', views.api_agregar_productos_orden_facturada, name='api_agregar_productos_orden_facturada'),
    path('api/mesa/<int:mesa_id>/orden/', views.api_get_orden_por_mesa, name='api_get_orden_por_mesa'),
    path('api/orden/<int:orden_id>/servida/', views.api_marcar_orden_servida, name='api_marcar_orden_servida'),

    # === API MESERO ===
    path('api/mesero/ordenes/', views.api_get_ordenes_mesero, name='api_get_ordenes_mesero'),
    path('api/mesero/todas-ordenes/', views.api_get_todas_ordenes_mesero, name='api_get_todas_ordenes_mesero'),
    path('api/mesero/orden/<int:orden_id>/marcar-lista/', views.api_marcar_orden_lista_manual, name='api_marcar_orden_lista_manual'),
    path('api/mesero/orden/<int:orden_id>/entregar/', views.api_marcar_orden_entregada, name='api_marcar_orden_entregada'),
    path('api/mesero/mesas-ocupadas/', views.api_get_mesas_ocupadas, name='api_get_mesas_ocupadas'),

    # === API COCINA ===
    path('api/cocina/ordenes/', views.api_get_ordenes_cocina, name='api_get_ordenes_cocina'),
    path('api/cocina/producto/<int:producto_orden_id>/listo/', views.api_marcar_producto_listo_tiempo_real, name='api_marcar_producto_listo'),
    path('api/cocina/producto/<int:producto_orden_id>/decrementar/', views.api_decrementar_producto_tiempo_real, name='api_decrementar_producto'),
    path('api/cocina/orden/<int:orden_id>/servida/', views.api_marcar_orden_servida, name='api_marcar_orden_servida'),

    # === API FACTURAS ===
    path('api/factura/orden/<int:orden_id>/', views.api_get_factura_por_orden, name='api_get_factura_por_orden'),
    path('api/orden/<int:orden_id>/agregar-productos-facturada/', views.api_agregar_productos_orden_facturada, name='api_agregar_productos_orden_facturada'),
    # En core/urls.py debe existir:
    path('api/orden/<int:orden_id>/agregar-productos/', views.api_agregar_productos_orden, name='api_agregar_productos_orden'),

    # === LONG POLLING (TIEMPO REAL) ===
    path('api/longpolling/cocina/', views.api_longpolling_cocina, name='api_longpolling_cocina'),
    path('api/longpolling/meseros/', views.api_longpolling_meseros, name='api_longpolling_meseros'),

    # === SISTEMA Y DEBUG ===
    path('api/sistema/estadisticas/', views.api_estadisticas_sistema, name='api_estadisticas_sistema'),
]