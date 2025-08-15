# core/services/cocina_service.py
"""
Servicio de negocio para operaciones específicas de la cocina.
Contiene toda la lógica relacionada con la preparación de alimentos y gestión del estado de productos.
"""

from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from ..models import Orden, OrdenProducto, Producto
from ..utils import (
    obtener_datos_completos_orden, notificar_cambio_cocina, 
    notificar_cambio_stock, calcular_total_orden
)


class CocinaService:
    """Servicio que maneja toda la lógica de negocio específica de la cocina."""
    
    def __init__(self):
        self.ESTADOS_ORDEN_ACTIVA = ['EN_PROCESO', 'NUEVA', 'LISTA']
        self.ESTADOS_PRODUCTO_PENDIENTE = ['PENDIENTE']
    
    # === GESTIÓN DE PRODUCTOS EN ÓRDENES ===
    
    @transaction.atomic
    def marcar_producto_listo(self, producto_orden_id, usuario_cocina):
        """
        Marca un producto específico como listo y actualiza el estado de la orden si corresponde.
        
        Args:
            producto_orden_id: ID del OrdenProducto a marcar como listo
            usuario_cocina: Usuario de cocina que ejecuta la acción
            
        Returns:
            dict: Resultado de la operación con información detallada
        """
        try:
            producto_orden = OrdenProducto.objects.select_related('orden', 'producto').get(
                id=producto_orden_id
            )
            
            # Validaciones de estado
            if producto_orden.estado == 'LISTO':
                return {
                    'success': False,
                    'errores': ['El producto ya está marcado como listo']
                }
            
            orden = producto_orden.orden
            if orden.estado not in self.ESTADOS_ORDEN_ACTIVA:
                return {
                    'success': False,
                    'errores': [f'No se puede modificar orden con estado: {orden.estado}']
                }
            
            # Marcar producto como listo
            producto_nombre = producto_orden.producto.nombre
            producto_orden.estado = 'LISTO'
            producto_orden.listo_en = timezone.now()
            producto_orden.save()
            
            # Verificar si la orden está completa
            productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
            orden_completa = productos_pendientes == 0
            
            if orden_completa:
                orden.estado = 'LISTA'
                orden.listo_en = timezone.now()
                orden.save()
            
            # Notificar cambios
            notificar_cambio_cocina()
            
            # Preparar respuesta
            mensaje = (
                f'¡Orden #{orden.id} completa y lista para servir!' if orden_completa
                else f'Producto {producto_nombre} completado. Faltan {productos_pendientes} productos.'
            )
            
            return {
                'success': True,
                'producto_listo': True,
                'producto_nombre': producto_nombre,
                'orden_completa': orden_completa,
                'productos_restantes': productos_pendientes,
                'orden_id': orden.id,
                'mensaje': mensaje,
                'orden_data': obtener_datos_completos_orden(orden)
            }
            
        except OrdenProducto.DoesNotExist:
            return {
                'success': False,
                'errores': ['Producto de orden no encontrado']
            }
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error interno: {str(e)}']
            }
    
    @transaction.atomic
    def decrementar_producto(self, producto_orden_id, usuario_cocina):
        """
        Decrementa la cantidad de un producto en preparación y devuelve 1 unidad al inventario.
        Esto representa que el cocinero ya entregó una unidad pero el producto sigue en preparación.
        
        Args:
            producto_orden_id: ID del OrdenProducto a decrementar
            usuario_cocina: Usuario de cocina que ejecuta la acción
            
        Returns:
            dict: Resultado de la operación
        """
        try:
            producto_orden = OrdenProducto.objects.select_related('orden', 'producto').get(
                id=producto_orden_id
            )
            
            orden = producto_orden.orden
            
            # Validaciones de estado
            if orden.estado not in ['EN_PROCESO', 'NUEVA']:
                return {
                    'success': False,
                    'errores': [f'No se puede modificar orden con estado: {orden.estado}']
                }
            
            if producto_orden.estado == 'LISTO':
                return {
                    'success': False,
                    'errores': ['No se puede decrementar un producto ya completado']
                }
            
            if producto_orden.cantidad <= 1:
                return {
                    'success': False,
                    'errores': ['No se puede decrementar: solo queda 1 unidad. Usa "Marcar Listo" para completar.']
                }
            
            # Ejecutar decremento
            producto_nombre = producto_orden.producto.nombre
            cantidad_original = producto_orden.cantidad
            
            # Decrementar cantidad en la orden
            producto_orden.cantidad -= 1
            producto_orden.save()
            
            # Devolver 1 unidad al inventario
            producto = producto_orden.producto
            producto.cantidad += 1
            producto.save()
            
            # Verificar productos pendientes en la orden
            productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
            
            # Notificar cambios
            notificar_cambio_cocina()
            notificar_cambio_stock()
            
            mensaje = (
                f'{producto_nombre} decrementado: queda {producto_orden.cantidad} por preparar '
                f'(entregaste 1 de {cantidad_original})'
            )
            
            return {
                'success': True,
                'nueva_cantidad': producto_orden.cantidad,
                'cantidad_entregada': cantidad_original - producto_orden.cantidad,
                'producto_sigue_pendiente': True,
                'mensaje': mensaje,
                'productos_pendientes_restantes': productos_pendientes,
                'orden_data': obtener_datos_completos_orden(orden)
            }
            
        except OrdenProducto.DoesNotExist:
            return {
                'success': False,
                'errores': ['Producto de orden no encontrado']
            }
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error interno: {str(e)}']
            }
    
    @transaction.atomic
    def marcar_orden_completa(self, orden_id, usuario_cocina):
        """
        Marca todos los productos pendientes de una orden como listos.
        Útil para completar una orden de una vez.
        """
        try:
            orden = Orden.objects.get(id=orden_id)
            
            if orden.estado not in self.ESTADOS_ORDEN_ACTIVA:
                return {
                    'success': False,
                    'errores': [f'No se puede modificar orden con estado: {orden.estado}']
                }
            
            if orden.estado == 'LISTA':
                return {
                    'success': False,
                    'errores': ['La orden ya está marcada como lista']
                }
            
            # Marcar todos los productos pendientes como listos
            productos_actualizados = 0
            productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE')
            
            for producto_orden in productos_pendientes:
                producto_orden.estado = 'LISTO'
                producto_orden.listo_en = timezone.now()
                producto_orden.save()
                productos_actualizados += 1
            
            # Marcar orden como lista si había productos pendientes
            if productos_actualizados > 0:
                orden.estado = 'LISTA'
                orden.listo_en = timezone.now()
                orden.save()
            
            # Notificar cambios
            notificar_cambio_cocina()
            
            return {
                'success': True,
                'productos_actualizados': productos_actualizados,
                'orden_completa': True,
                'mensaje': f'Orden #{orden_id} marcada como lista con {productos_actualizados} productos actualizados'
            }
            
        except Orden.DoesNotExist:
            return {
                'success': False,
                'errores': ['Orden no encontrada']
            }
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error interno: {str(e)}']
            }
    
    # === CONSULTAS Y REPORTES DE COCINA ===
    
    def obtener_ordenes_activas_cocina(self):
        """
        Obtiene todas las órdenes activas para mostrar en el dashboard de cocina.
        Incluye información detallada sobre productos y tiempos.
        """
        try:
            ordenes = Orden.objects.filter(
                estado__in=self.ESTADOS_ORDEN_ACTIVA
            ).select_related('mesa', 'mesero').prefetch_related(
                'productos_ordenados__producto'
            ).order_by('creado_en')
            
            lista_ordenes = []
            for orden in ordenes:
                try:
                    orden_data = self._procesar_orden_para_cocina(orden)
                    lista_ordenes.append(orden_data)
                except Exception as e:
                    print(f"ERROR procesando orden {orden.id} para cocina: {str(e)}")
                    continue
            
            return {
                'success': True,
                'ordenes': lista_ordenes,
                'total_ordenes': len(lista_ordenes)
            }
            
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error obteniendo órdenes de cocina: {str(e)}']
            }
    
    def obtener_productos_pendientes_por_prioridad(self):
        """
        Obtiene productos pendientes organizados por prioridad de preparación.
        """
        try:
            # Obtener todos los productos pendientes de órdenes activas
            productos_pendientes = OrdenProducto.objects.filter(
                orden__estado__in=self.ESTADOS_ORDEN_ACTIVA,
                estado='PENDIENTE'
            ).select_related('orden', 'producto', 'orden__mesa', 'orden__mesero').order_by('orden__creado_en')
            
            # Organizar por prioridad
            productos_urgentes = []  # Órdenes con más de 30 minutos
            productos_normales = []  # Órdenes normales
            productos_nuevos = []    # Órdenes recientes (menos de 10 minutos)
            
            ahora = timezone.now()
            
            for po in productos_pendientes:
                tiempo_orden = (ahora - po.orden.creado_en).total_seconds() / 60  # en minutos
                
                producto_info = {
                    'id': po.id,
                    'nombre': po.producto.nombre,
                    'cantidad': po.cantidad,
                    'observaciones': self._limpiar_observaciones_producto(po.observaciones),
                    'orden_id': po.orden.id,
                    'mesa': po.orden.mesa.numero,
                    'mesero': po.orden.mesero.nombre,
                    'tiempo_orden': int(tiempo_orden),
                    'agregado_despues': self._es_producto_agregado_despues(po),
                    'tiempo_preparacion_estimado': po.producto.tiempo_preparacion if hasattr(po.producto, 'tiempo_preparacion') else 15
                }
                
                if tiempo_orden > 30:
                    productos_urgentes.append(producto_info)
                elif tiempo_orden < 10:
                    productos_nuevos.append(producto_info)
                else:
                    productos_normales.append(producto_info)
            
            return {
                'success': True,
                'productos_por_prioridad': {
                    'urgentes': productos_urgentes,
                    'normales': productos_normales,
                    'nuevos': productos_nuevos
                },
                'total_productos': len(productos_pendientes),
                'resumen': {
                    'urgentes_count': len(productos_urgentes),
                    'normales_count': len(productos_normales),
                    'nuevos_count': len(productos_nuevos)
                }
            }
            
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error obteniendo productos por prioridad: {str(e)}']
            }
    
    def obtener_estadisticas_cocina(self, fecha_inicio=None, fecha_fin=None):
        """
        Obtiene estadísticas de rendimiento de la cocina en un período.
        """
        try:
            if not fecha_fin:
                fecha_fin = timezone.now()
            if not fecha_inicio:
                fecha_inicio = fecha_fin.replace