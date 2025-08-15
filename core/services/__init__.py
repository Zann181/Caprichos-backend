# core/services/__init__.py
"""
Servicios de negocio del sistema de restaurante.
Contiene la lógica de negocio organizada por roles y responsabilidades.
"""

from .mesero_service import MeseroService
from .cocina_service import CocinaService
from .cajero_service import CajeroService
from .admin_service import AdminService

# Instancias singleton de los servicios
mesero_service = MeseroService()
cocina_service = CocinaService()
cajero_service = CajeroService()
admin_service = AdminService()

__all__ = [
    'MeseroService',
    'CocinaService', 
    'CajeroService',
    'AdminService',
    'mesero_service',
    'cocina_service',
    'cajero_service',
    'admin_service',
]