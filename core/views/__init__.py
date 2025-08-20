# core/views/__init__.py
"""
Importaciones centralizadas para mantener compatibilidad con urls.py existente.
Todas las vistas se importan aquí para que funcionen transparentemente.
"""

# Importar todas las vistas de autenticación y dashboards
from .auth_views import (
    UserLoginView,
    UserLogoutView,
    dashboard_redirect,
    dashboard_admin,
    dashboard_cajero,
    dashboard_cocinero,
    dashboard_mesero,
    mesero_nuevo_pedido,
    mesero_modificar_orden,
    mesero_vista_cocina,
    mesero_mis_ordenes,
    acceso_denegado_view,
)

# Importar todas las vistas CRUD
from .crud_views import (
    api_productos_list_create,
    api_producto_detail,
)

# Importar todas las APIs
from .api_views import (
    # APIs de órdenes
    api_crear_orden_tiempo_real,
    api_agregar_productos_orden,
    api_agregar_productos_orden_facturada,
    api_get_orden_por_mesa,
    api_marcar_orden_servida,
    
    # APIs de mesero
    api_get_ordenes_mesero,
    api_get_todas_ordenes_mesero,
    api_marcar_orden_lista_manual,
    api_marcar_orden_entregada,
    api_get_mesas_ocupadas,
    api_get_mesas_ocupadas_detallado,
    
    # APIs de cocina
    api_get_ordenes_cocina,
    api_marcar_producto_listo_tiempo_real,
    api_decrementar_producto_tiempo_real,
    
    # APIs de facturas
    api_get_factura_por_orden,
    
    # Long polling
    api_longpolling_cocina,
    api_longpolling_meseros,
    
    # Sistema y debug
    api_estadisticas_sistema,
    api_debug_debounce_status,

    api_get_reservas_cocina,  # ✅ NUEVA VISTA IMPORTADA
    api_marcar_factura_pagada,
)

# Funciones utilitarias que podrían ser importadas
from .api_views import (
    calcular_tiempo_transcurrido,
    extraer_info_cliente_domicilio,
    extraer_info_cliente_reserva,
    limpiar_debounces_usuario,

)

__all__ = [
    # Auth y dashboards
    'UserLoginView',
    'UserLogoutView', 
    'dashboard_redirect',
    'dashboard_admin',
    'dashboard_cajero',
    'dashboard_cocinero',
    'dashboard_mesero',
    'mesero_nuevo_pedido',
    'mesero_modificar_orden',
    'mesero_vista_cocina',
    'mesero_mis_ordenes',
    'acceso_denegado_view',
    
    # CRUD
    'api_productos_list_create',
    'api_producto_detail',
    
    # APIs de órdenes
    'api_crear_orden_tiempo_real',
    'api_agregar_productos_orden',
    'api_agregar_productos_orden_facturada',
    'api_get_orden_por_mesa',
    'api_marcar_orden_servida',
    
    # APIs de mesero
    'api_get_ordenes_mesero',
    'api_get_todas_ordenes_mesero',
    'api_marcar_orden_lista_manual',
    'api_marcar_orden_entregada',
    'api_get_mesas_ocupadas',
    'api_get_mesas_ocupadas_detallado',
    
    # APIs de cocina
    'api_get_ordenes_cocina',
    'api_marcar_producto_listo_tiempo_real',
    'api_decrementar_producto_tiempo_real',
    
    # APIs de facturas
    'api_get_factura_por_orden',
    
    # Long polling
    'api_longpolling_cocina',
    'api_longpolling_meseros',
    
    # Sistema
    'api_estadisticas_sistema',
    'api_debug_debounce_status',
    
    # Utilitarias
    'calcular_tiempo_transcurrido',
    'extraer_info_cliente_domicilio',
    'extraer_info_cliente_reserva',
    'limpiar_debounces_usuario',
    'api_get_reservas_cocina',  # ✅ NUEVA VISTA EXPORTADA
    'api_marcar_factura_pagada',
]