# core/services/mesero_service.py
"""
Servicio de negocio para operaciones específicas del mesero.
Contiene toda la lógica relacionada con la gestión de órdenes, mesas y entregas.
"""

import re
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from ..models import Orden, OrdenProducto, Mesa, Producto, Factura
from ..utils import (
    calcular_total_orden, obtener_datos_completos_orden,
    notificar_cambio_cocina, notificar_cambio_stock
)


class MeseroService:
    """Servicio que maneja toda la lógica de negocio específica del mesero."""
    
    def __init__(self):
        self.MESA_DOMICILIO = 0
        self.MESA_RESERVA = 50
    
    # === GESTIÓN DE ÓRDENES ===
    
    @transaction.atomic
    def crear_orden_completa(self, mesero, mesa_id, productos_pedido, observaciones_orden=""):
        """
        Crea una orden completa con validaciones de negocio.
        
        Args:
            mesero: Usuario mesero que crea la orden
            mesa_id: ID de la mesa
            productos_pedido: Lista de productos con formato [{'id': int, 'cantidad': int, 'observaciones': str}]
            observaciones_orden: Observaciones generales de la orden
            
        Returns:
            dict: {'success': bool, 'orden': Orden, 'mensaje': str, 'errores': list}
        """
        try:
            # Validar mesa
            try:
                mesa = Mesa.objects.get(id=mesa_id, is_active=True)
            except Mesa.DoesNotExist:
                return {
                    'success': False,
                    'errores': ['Mesa no encontrada o inactiva'],
                    'orden': None
                }
            
            # Validar productos
            if not productos_pedido:
                return {
                    'success': False,
                    'errores': ['El pedido debe tener al menos un producto'],
                    'orden': None
                }
            
            # Validar stock y existencia de productos
            productos_validados = []
            errores_validacion = []
            
            for item in productos_pedido:
                try:
                    producto = Producto.objects.get(
                        id=item['id'], 
                        is_active=True, 
                        is_available=True
                    )
                    
                    cantidad = int(item['cantidad'])
                    if cantidad <= 0:
                        errores_validacion.append(f'{producto.nombre}: Cantidad debe ser mayor a 0')
                        continue
                    
                    if producto.cantidad < cantidad:
                        errores_validacion.append(
                            f'{producto.nombre}: Stock insuficiente. Disponible: {producto.cantidad}, solicitado: {cantidad}'
                        )
                        continue
                    
                    productos_validados.append({
                        'producto': producto,
                        'cantidad': cantidad,
                        'observaciones': item.get('observaciones', '').strip()
                    })
                    
                except Producto.DoesNotExist:
                    errores_validacion.append(f'Producto con ID {item["id"]} no encontrado')
                except (ValueError, KeyError):
                    errores_validacion.append(f'Datos inválidos para producto {item.get("id", "desconocido")}')
            
            if errores_validacion:
                return {
                    'success': False,
                    'errores': errores_validacion,
                    'orden': None
                }
            
            # Verificar disponibilidad de mesa para mesas físicas
            if mesa.numero not in [self.MESA_DOMICILIO, self.MESA_RESERVA]:
                if mesa.estado != 'LIBRE':
                    return {
                        'success': False,
                        'errores': [f'La mesa {mesa.numero} no está disponible'],
                        'orden': None
                    }
            
            # Crear la orden
            nueva_orden = Orden.objects.create(
                mesero=mesero,
                mesa=mesa,
                estado='EN_PROCESO',
                observaciones=observaciones_orden
            )
            
            # Agregar productos y actualizar stock
            productos_creados = []
            for item_validado in productos_validados:
                producto = item_validado['producto']
                cantidad = item_validado['cantidad']
                observaciones = item_validado['observaciones']
                
                producto_orden = OrdenProducto.objects.create(
                    orden=nueva_orden,
                    producto=producto,
                    cantidad=cantidad,
                    precio_unitario=producto.precio,
                    observaciones=observaciones,
                    estado='PENDIENTE'
                )
                productos_creados.append(producto_orden)
                
                # Actualizar stock
                producto.cantidad -= cantidad
                producto.save()
            
            # Ocupar mesa si es física
            if mesa.numero not in [self.MESA_DOMICILIO, self.MESA_RESERVA]:
                mesa.estado = 'OCUPADA'
                mesa.save()
            
            # Notificar cambios
            notificar_cambio_cocina()
            notificar_cambio_stock()
            
            return {
                'success': True,
                'orden': nueva_orden,
                'productos_creados': len(productos_creados),
                'mensaje': f'Orden #{nueva_orden.id} creada exitosamente con {len(productos_creados)} productos'
            }
            
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error interno: {str(e)}'],
                'orden': None
            }
    
    @transaction.atomic
    def agregar_productos_a_orden(self, orden_id, productos_nuevos, mesero):
        """
        Agrega productos a una orden existente.
        Maneja automáticamente órdenes con factura pendiente.
        """
        try:
            orden = Orden.objects.get(id=orden_id)
            
            # Verificar permisos
            if orden.mesero != mesero and not mesero.is_superuser:
                return {
                    'success': False,
                    'errores': ['Solo puedes modificar tus propias órdenes']
                }
            
            # Verificar si tiene factura pendiente
            tiene_factura_pendiente = False
            factura = None
            
            try:
                factura = orden.factura
                if factura.estado_pago in ['NO_PAGADA', 'PARCIAL']:
                    tiene_factura_pendiente = True
            except Factura.DoesNotExist:
                pass
            
            # Validar que la orden pueda ser modificada
            if orden.estado == 'SERVIDA' and not tiene_factura_pendiente:
                return {
                    'success': False,
                    'errores': ['No se puede modificar una orden servida con factura pagada']
                }
            
            # Validar productos nuevos
            productos_validados = []
            errores_validacion = []
            
            for item in productos_nuevos:
                try:
                    producto = Producto.objects.get(id=item['id'], is_active=True, is_available=True)
                    cantidad = int(item['cantidad'])
                    
                    if cantidad <= 0:
                        errores_validacion.append(f'{producto.nombre}: Cantidad inválida')
                        continue
                    
                    if producto.cantidad < cantidad:
                        errores_validacion.append(
                            f'{producto.nombre}: Stock insuficiente. Disponible: {producto.cantidad}'
                        )
                        continue
                    
                    productos_validados.append({
                        'producto': producto,
                        'cantidad': cantidad,
                        'observaciones': item.get('observaciones', '').strip()
                    })
                    
                except Producto.DoesNotExist:
                    errores_validacion.append(f'Producto con ID {item["id"]} no encontrado')
                except (ValueError, KeyError):
                    errores_validacion.append(f'Datos inválidos para producto {item.get("id")}')
            
            if errores_validacion:
                return {
                    'success': False,
                    'errores': errores_validacion
                }
            
            # Determinar marcador según tipo de modificación
            if tiene_factura_pendiente:
                marcador_obs = "AGREGADO_POST_FACTURA"
                tipo_agregado = "post-factura"
            else:
                marcador_obs = "AGREGADO_DESPUES"
                tipo_agregado = "después de creación"
            
            # Agregar productos
            productos_agregados = []
            total_agregado = 0
            
            for item_validado in productos_validados:
                producto = item_validado['producto']
                cantidad = item_validado['cantidad']
                observaciones_usuario = item_validado['observaciones']
                
                # Preparar observaciones finales
                if observaciones_usuario:
                    obs_final = f"{marcador_obs}|{observaciones_usuario}"
                else:
                    obs_final = marcador_obs
                
                # Crear OrdenProducto
                nuevo_producto_orden = OrdenProducto.objects.create(
                    orden=orden,
                    producto=producto,
                    cantidad=cantidad,
                    precio_unitario=producto.precio,
                    observaciones=obs_final,
                    estado='PENDIENTE'
                )
                
                productos_agregados.append(nuevo_producto_orden)
                total_agregado += cantidad * producto.precio
                
                # Actualizar stock
                producto.cantidad -= cantidad
                producto.save()
            
            # Actualizar factura si existe
            nueva_factura_total = None
            if tiene_factura_pendiente and factura:
                factura.subtotal += total_agregado
                factura.total += total_agregado
                factura.save()
                nueva_factura_total = float(factura.total)
            
            # Actualizar estado de la orden
            if orden.estado == 'LISTA':
                orden.estado = 'EN_PROCESO'
                orden.listo_en = None
                orden.save()
            elif orden.estado == 'SERVIDA' and tiene_factura_pendiente:
                orden.estado = 'EN_PROCESO'
                orden.save()
            
            # Notificar cambios
            notificar_cambio_cocina()
            notificar_cambio_stock()
            
            return {
                'success': True,
                'productos_agregados': len(productos_agregados),
                'total_agregado': total_agregado,
                'tiene_factura_pendiente': tiene_factura_pendiente,
                'nueva_factura_total': nueva_factura_total,
                'tipo_agregado': tipo_agregado,
                'mensaje': f'Se agregaron {len(productos_agregados)} productos a la orden'
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
    
    @transaction.atomic
    def marcar_orden_como_lista(self, orden_id, mesero):
        """Marca manualmente una orden como lista (todos los productos listos)."""
        try:
            orden = Orden.objects.get(id=orden_id)
            
            # Verificar permisos
            if orden.mesero != mesero and not mesero.is_superuser:
                return {
                    'success': False,
                    'errores': ['Solo puedes marcar como lista tus propias órdenes']
                }
            
            if orden.estado == 'LISTA':
                return {
                    'success': False,
                    'errores': ['La orden ya está marcada como lista']
                }
            
            if orden.estado == 'SERVIDA':
                return {
                    'success': False,
                    'errores': ['No se puede modificar una orden ya servida']
                }
            
            # Marcar todos los productos como listos
            productos_actualizados = 0
            for producto_orden in orden.productos_ordenados.filter(estado='PENDIENTE'):
                producto_orden.estado = 'LISTO'
                producto_orden.listo_en = timezone.now()
                producto_orden.save()
                productos_actualizados += 1
            
            # Marcar orden como lista
            orden.estado = 'LISTA'
            orden.listo_en = timezone.now()
            orden.save()
            
            # Notificar cambios
            notificar_cambio_cocina()
            
            return {
                'success': True,
                'productos_actualizados': productos_actualizados,
                'mensaje': f'Orden #{orden_id} marcada como lista exitosamente'
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
    
    @transaction.atomic
    def entregar_orden(self, orden_id, mesero):
        """Marca una orden como entregada y genera/actualiza su factura."""
        try:
            orden = Orden.objects.get(id=orden_id)
            
            # Verificar permisos
            if orden.mesero != mesero and not mesero.is_superuser:
                return {
                    'success': False,
                    'errores': ['Solo puedes entregar tus propias órdenes']
                }
            
            if orden.estado != 'LISTA':
                return {
                    'success': False,
                    'errores': [f'La orden debe estar LISTA para entregarla. Estado actual: {orden.estado}']
                }
            
            # Verificar que todos los productos estén listos
            productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
            if productos_pendientes > 0:
                return {
                    'success': False,
                    'errores': [f'Aún hay {productos_pendientes} productos pendientes']
                }
            
            # Calcular total
            total_orden = calcular_total_orden(orden)
            
            # Marcar como servida
            orden.estado = 'SERVIDA'
            orden.save()
            
            # Liberar la mesa si es física
            mesa = orden.mesa
            if mesa.numero not in [self.MESA_DOMICILIO, self.MESA_RESERVA]:
                mesa.estado = 'LIBRE'
                mesa.save()
            
            # Gestionar factura
            try:
                # Intentar obtener factura existente
                factura = Factura.objects.get(orden=orden)
                factura.estado_pago = 'NO_PAGADA'
                factura.subtotal = total_orden
                factura.total = total_orden
                factura.save()
                factura_creada = False
            except Factura.DoesNotExist:
                # Crear nueva factura
                factura = Factura.objects.create(
                    orden=orden,
                    subtotal=total_orden,
                    total=total_orden,
                    estado_pago='NO_PAGADA'
                )
                factura_creada = True
            
            # Notificar cambios
            notificar_cambio_cocina()
            
            return {
                'success': True,
                'factura_id': factura.id,
                'factura_creada': factura_creada,
                'mesa_liberada': mesa.numero not in [self.MESA_DOMICILIO, self.MESA_RESERVA],
                'total': float(total_orden),
                'mensaje': f'Orden #{orden_id} entregada exitosamente'
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
    
    # === CONSULTAS Y REPORTES ===
    
    def obtener_ordenes_activas_mesero(self, mesero):
        """Obtiene las órdenes activas de un mesero específico."""
        try:
            ordenes = Orden.objects.filter(
                mesero=mesero,
                estado__in=['EN_PROCESO', 'LISTA']
            ).order_by('-creado_en')
            
            ordenes_data = []
            for orden in ordenes:
                orden_data = obtener_datos_completos_orden(orden)
                
                # Agregar información específica del mesero
                productos_listos = orden.productos_ordenados.filter(estado='LISTO').count()
                productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
                productos_agregados = orden.productos_ordenados.filter(
                    observaciones__icontains='AGREGADO_DESPUES'
                ).count()
                
                orden_data.update({
                    'tiene_productos_listos': productos_listos > 0,
                    'productos_listos_count': productos_listos,
                    'productos_pendientes_count': productos_pendientes,
                    'productos_agregados_count': productos_agregados,
                    'necesita_atencion': productos_listos > 0,
                    'puede_marcar_lista': productos_pendientes == 0 and orden.estado == 'EN_PROCESO',
                    'puede_entregar': orden.estado == 'LISTA'
                })
                
                ordenes_data.append(orden_data)
            
            return {
                'success': True,
                'ordenes': ordenes_data
            }
            
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error obteniendo órdenes: {str(e)}']
            }
    
    def obtener_todas_ordenes_mesero(self, mesero, filtro='todas'):
        """
        Obtiene todas las órdenes de un mesero con filtros específicos.
        
        Filtros disponibles:
        - 'todas': Últimas 7 días (limitado)
        - 'activas': EN_PROCESO, LISTA
        - 'servidas': SERVIDA con factura pagada
        - 'listas': LISTA
        - 'en-preparacion': EN_PROCESO
        - 'no-pagadas': SERVIDA con factura pendiente
        - 'domicilios': Mesa 0
        - 'reservas': Mesa 50
        """
        try:
            ordenes_query = Orden.objects.filter(mesero=mesero)
            
            # Aplicar filtros
            if filtro == 'activas':
                ordenes_query = ordenes_query.filter(estado__in=['EN_PROCESO', 'LISTA'])
            elif filtro == 'servidas':
                ordenes_query = ordenes_query.filter(
                    estado='SERVIDA', 
                    factura__estado_pago='PAGADA'
                )
            elif filtro == 'listas':
                ordenes_query = ordenes_query.filter(estado='LISTA')
            elif filtro == 'en-preparacion':
                ordenes_query = ordenes_query.filter(estado='EN_PROCESO')
            elif filtro == 'no-pagadas':
                ordenes_query = ordenes_query.filter(
                    estado='SERVIDA',
                    factura__estado_pago__in=['NO_PAGADA', 'PARCIAL']
                )
            elif filtro == 'domicilios':
                ordenes_query = ordenes_query.filter(mesa__numero=self.MESA_DOMICILIO)
            elif filtro == 'reservas':
                ordenes_query = ordenes_query.filter(mesa__numero=self.MESA_RESERVA)
            elif filtro == 'todas':
                # Limitar a últimos 7 días para performance
                fecha_limite = timezone.now() - timedelta(days=7)
                ordenes_query = ordenes_query.filter(creado_en__gte=fecha_limite)
            
            # Ordenar y limitar
            ordenes = ordenes_query.order_by('-creado_en')[:50]
            
            ordenes_data = []
            for orden in ordenes:
                orden_data = self._enriquecer_datos_orden_mesero(orden)
                ordenes_data.append(orden_data)
            
            return {
                'success': True,
                'ordenes': ordenes_data,
                'filtro_aplicado': filtro,
                'total_encontradas': len(ordenes_data)
            }
            
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error obteniendo órdenes: {str(e)}']
            }
    
    def obtener_mesas_ocupadas(self, incluir_detalle_cliente=True):
        """Obtiene todas las mesas ocupadas incluyendo domicilios y reservas."""
        try:
            mesas_data = []
            
            # Mesas físicas ocupadas
            mesas_fisicas = Mesa.objects.filter(
                is_active=True,
                estado='OCUPADA'
            ).exclude(numero__in=[self.MESA_DOMICILIO, self.MESA_RESERVA])
            
            for mesa in mesas_fisicas:
                orden = Orden.objects.filter(
                    mesa=mesa,
                    estado__in=['EN_PROCESO', 'LISTA', 'NUEVA']
                ).first()
                
                if orden:
                    mesas_data.append({
                        'id': mesa.id,
                        'numero': mesa.numero,
                        'ubicacion': mesa.ubicacion,
                        'capacidad': mesa.capacidad,
                        'productos_count': orden.productos_ordenados.count(),
                        'tiene_orden': True,
                        'orden_id': orden.id,
                        'es_domicilio': False,
                        'es_reserva': False,
                        'tipo': 'MESA_FISICA'
                    })
            
            # Mesas especiales (domicilio y reservas)
            mesas_especiales = Mesa.objects.filter(
                is_active=True,
                numero__in=[self.MESA_DOMICILIO, self.MESA_RESERVA]
            )
            
            for mesa_especial in mesas_especiales:
                ordenes_activas = self._obtener_ordenes_activas_mesa_especial(mesa_especial)
                
                if ordenes_activas.exists():
                    for i, orden in enumerate(ordenes_activas):
                        mesa_info = self._crear_info_mesa_especial(
                            mesa_especial, orden, i, incluir_detalle_cliente
                        )
                        mesas_data.append(mesa_info)
                else:
                    # Mesa especial disponible
                    tipo_descripcion = 'Domicilio' if mesa_especial.numero == self.MESA_DOMICILIO else 'Reserva'
                    mesas_data.append({
                        'id': mesa_especial.id,
                        'numero': mesa_especial.numero,
                        'ubicacion': f'{tipo_descripcion} (Disponible)',
                        'capacidad': 999,
                        'productos_count': 0,
                        'tiene_orden': False,
                        'orden_id': None,
                        'es_domicilio': mesa_especial.numero == self.MESA_DOMICILIO,
                        'es_reserva': mesa_especial.numero == self.MESA_RESERVA,
                        'tipo': 'MESA_ESPECIAL_LIBRE'
                    })
            
            return {
                'success': True,
                'mesas': mesas_data,
                'total_mesas': len(mesas_data)
            }
            
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error obteniendo mesas: {str(e)}']
            }
    
    def obtener_orden_por_mesa(self, mesa_id):
        """Obtiene la orden activa de una mesa específica."""
        try:
            mesa = Mesa.objects.get(id=mesa_id, is_active=True)
            
            # Buscar orden activa O servida con factura no pagada
            orden = Orden.objects.filter(
                Q(mesa=mesa) & 
                (Q(estado__in=['EN_PROCESO', 'LISTA', 'NUEVA']) | 
                 Q(estado='SERVIDA', factura__estado_pago__in=['NO_PAGADA', 'PARCIAL']))
            ).distinct().first()
            
            if not orden:
                return {
                    'success': False,
                    'errores': ['No hay orden activa o con pago pendiente en esta mesa']
                }
            
            # Obtener datos completos de la orden
            orden_data = obtener_datos_completos_orden(orden)
            
            # Verificar si tiene factura pendiente
            tiene_factura_pendiente = False
            try:
                if orden.factura.estado_pago in ['NO_PAGADA', 'PARCIAL']:
                    tiene_factura_pendiente = True
            except:
                pass
            
            orden_data['tiene_factura_pendiente'] = tiene_factura_pendiente
            
            # Separar productos originales de agregados
            productos_originales = []
            productos_agregados = []
            
            for producto_data in orden_data['productos']:
                producto_orden = OrdenProducto.objects.get(id=producto_data['id'])
                if (producto_orden.observaciones and 
                    ('AGREGADO_DESPUES' in producto_orden.observaciones or 
                     'AGREGADO_POST_FACTURA' in producto_orden.observaciones)):
                    producto_data['agregado_despues'] = True
                    productos_agregados.append(producto_data)
                else:
                    producto_data['agregado_despues'] = False
                    productos_originales.append(producto_data)
            
            orden_data['productos_originales'] = productos_originales
            orden_data['productos_agregados'] = productos_agregados
            
            return {
                'success': True,
                'orden': orden_data
            }
            
        except Mesa.DoesNotExist:
            return {
                'success': False,
                'errores': ['Mesa no encontrada']
            }
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error obteniendo orden: {str(e)}']
            }
    
    # === MÉTODOS PRIVADOS DE APOYO ===
    
    def _obtener_ordenes_activas_mesa_especial(self, mesa):
        """Obtiene órdenes activas de una mesa especial (domicilio/reserva)."""
        ordenes_activas = Orden.objects.filter(
            mesa=mesa,
            estado__in=['EN_PROCESO', 'LISTA', 'NUEVA']
        )
        
        try:
            ordenes_no_pagadas = Orden.objects.filter(
                mesa=mesa,
                estado='SERVIDA'
            ).filter(
                factura__estado_pago__in=['NO_PAGADA', 'PARCIAL']
            )
            
            return ordenes_activas.union(ordenes_no_pagadas).order_by('-creado_en')
        except Exception:
            return ordenes_activas.order_by('-creado_en')
    
    def _crear_info_mesa_especial(self, mesa, orden, index, incluir_detalle_cliente):
        """Crea la información de una mesa especial con orden."""
        es_domicilio = mesa.numero == self.MESA_DOMICILIO
        
        if es_domicilio:
            tipo_descripcion = 'Domicilio'
            icono = '🏠'
            cliente_info = self._extraer_info_cliente_domicilio(orden.observaciones) if incluir_detalle_cliente else {}
        else:
            tipo_descripcion = 'Reserva'
            icono = '📅'
            cliente_info = self._extraer_info_cliente_reserva(orden.observaciones)