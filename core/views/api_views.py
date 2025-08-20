# core/views/api_views.py - VERSIÓN CORREGIDA
"""
APIs del sistema de restaurante - VERSIÓN CORREGIDA.
Contiene todas las APIs para órdenes, mesero, cocina, facturas y long polling.
"""

import json
import time
import re
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone
from django.db.models import Q

from ..decorators import debounce_request, critical_operation, form_debounce
from ..models import Producto, CategoriaProducto, Mesa, Orden, OrdenProducto, Factura
from ..utils import (
    long_polling_cocina, long_polling_meseros, obtener_todas_ordenes_cocina,
    obtener_stock_productos, notificar_cambio_cocina, notificar_cambio_stock,
    obtener_estadisticas_sistema, obtener_datos_completos_orden,
    calcular_total_orden,
)


# === FUNCIONES UTILITARIAS ===

def calcular_tiempo_transcurrido(fecha_creacion):
    """Calcula el tiempo transcurrido desde la creación"""
    ahora = timezone.now()
    if timezone.is_naive(fecha_creacion):
        fecha_creacion = timezone.make_aware(fecha_creacion)
    
    delta = ahora - fecha_creacion
    minutos = int(delta.total_seconds() / 60)
    
    if minutos < 60:
        return f"{minutos}min"
    else:
        horas = minutos // 60
        mins = minutos % 60
        return f"{horas}h {mins}m"


def extraer_info_cliente_domicilio(observaciones):
    """Extrae información del cliente de domicilio de las observaciones"""
    if not observaciones:
        return {'nombre': 'Cliente Domicilio', 'direccion': '', 'telefono': ''}
    
    try:
        # Buscar patrones en las observaciones
        nombre_match = re.search(r'Cliente:\s*([^,\n]+)', observaciones, re.IGNORECASE)
        telefono_match = re.search(r'Tel(?:éfono)?:\s*([^,\n]+)', observaciones, re.IGNORECASE)
        direccion_match = re.search(r'Dir(?:ección)?:\s*([^,\n]+)', observaciones, re.IGNORECASE)
        
        nombre_final = 'Cliente Domicilio'
        if nombre_match:
            nombre_final = nombre_match.group(1).strip()
        else:
            # Usar las primeras palabras como nombre
            palabras = re.split(r'[,\n]', observaciones)
            primera_linea = palabras[0] if palabras else ''
            if primera_linea and len(primera_linea.strip()) > 0:
                nombre_final = primera_linea.strip()[:30]
        
        direccion_final = ''
        if direccion_match:
            direccion_final = direccion_match.group(1).strip()
        else:
            direccion_final = observaciones[:50] + '...' if len(observaciones) > 50 else observaciones
        
        return {
            'nombre': nombre_final,
            'telefono': telefono_match.group(1).strip() if telefono_match else '',
            'direccion': direccion_final
        }
    except Exception as e:
        print(f"Error extrayendo info de domicilio: {e}")
        return {'nombre': 'Cliente Domicilio', 'direccion': observaciones[:50], 'telefono': ''}


def extraer_info_cliente_reserva(observaciones):
    """Extrae información del cliente de reserva de las observaciones"""
    if not observaciones:
        return {
            'nombre': 'Cliente Reserva', 
            'personas': 2, 
            'telefono': '', 
            'fecha_reserva': '', 
            'hora_reserva': '',
            'observaciones': ''
        }
    
    try:
        # Buscar patrones en las observaciones de reserva
        nombre_match = re.search(r'(?:Reserva|Cliente|Nombre):\s*([^,\n]+)', observaciones, re.IGNORECASE)
        telefono_match = re.search(r'Tel(?:éfono)?:\s*([^,\n]+)', observaciones, re.IGNORECASE)
        personas_match = re.search(r'Personas?:\s*(\d+)', observaciones, re.IGNORECASE)
        fecha_match = re.search(r'Fecha:\s*([^,\n]+)', observaciones, re.IGNORECASE)
        hora_match = re.search(r'Hora:\s*([^,\n]+)', observaciones, re.IGNORECASE)
        
        nombre_final = 'Cliente Reserva'
        if nombre_match:
            nombre_final = nombre_match.group(1).strip()
        else:
            # Usar las primeras palabras como nombre
            palabras = re.split(r'[,\n]', observaciones)
            primera_linea = palabras[0] if palabras else ''
            if primera_linea and len(primera_linea.strip()) > 0:
                nombre_final = primera_linea.strip()[:30]
        
        return {
            'nombre': nombre_final,
            'telefono': telefono_match.group(1).strip() if telefono_match else '',
            'personas': int(personas_match.group(1)) if personas_match else 2,
            'fecha_reserva': fecha_match.group(1).strip() if fecha_match else '',
            'hora_reserva': hora_match.group(1).strip() if hora_match else '',
            'observaciones': observaciones
        }
    except Exception as e:
        print(f"Error extrayendo info de reserva: {e}")
        return {
            'nombre': 'Cliente Reserva', 
            'personas': 2, 
            'telefono': '', 
            'fecha_reserva': '', 
            'hora_reserva': '',
            'observaciones': observaciones
        }


def limpiar_debounces_usuario(user_id):
    """Función utilitaria para limpiar debounces de un usuario específico"""
    try:
        from django.core.cache import cache
        from ..decorators import DEBOUNCE_CONFIG
        
        # Limpiar debounces conocidos del usuario
        acciones_comunes = [
            'api_crear_orden_tiempo_real',
            'api_agregar_productos_orden',
            'api_marcar_orden_entregada',
            'api_marcar_producto_listo_tiempo_real',
            'api_decrementar_producto_tiempo_real',
            'api_marcar_orden_lista_manual',
            'api_marcar_orden_servida'
        ]
        
        for accion in acciones_comunes:
            debounce_key = f"{DEBOUNCE_CONFIG['CACHE_PREFIX']}{user_id}:{accion}"
            cache.delete(debounce_key)
            
        print(f"🧹 Debounces limpiados para usuario {user_id}")
        return True
    except Exception as e:
        print(f"❌ Error limpiando debounces: {e}")
        return False


# === API ÓRDENES (CREAR Y GESTIONAR) ===

@require_POST
@login_required
@transaction.atomic
@critical_operation(delay=2.0, error_message="⚠️ Pedido en proceso. Espera 2 segundos antes de crear otro.")
def api_crear_orden_tiempo_real(request):
    """API para crear orden CON debounce crítico de 2 segundos"""
    try:
        data = json.loads(request.body)
        productos_pedido = data.get('productos', [])
        mesa = get_object_or_404(Mesa, id=data.get('mesa_id'))
        mesero = request.user

        if not productos_pedido: 
            return JsonResponse({'error': 'El pedido no tiene productos.'}, status=400)

        # Validación de stock
        for item in productos_pedido:
            producto = Producto.objects.get(id=item['id'])
            if producto.cantidad < item['cantidad']:
                return JsonResponse({'error': f'Stock insuficiente para {producto.nombre}.'}, status=400)

        # Creación de la orden
        nueva_orden = Orden.objects.create(
            mesero=mesero, 
            mesa=mesa, 
            estado='EN_PROCESO',
            observaciones=data.get('observaciones_orden', '')
        )
        
        for item in productos_pedido:
            producto = Producto.objects.get(id=item['id'])
            OrdenProducto.objects.create(
                orden=nueva_orden, 
                producto=producto, 
                cantidad=item['cantidad'], 
                precio_unitario=producto.precio,
                observaciones=item.get('observaciones', '')
            )
            # Descuento de inventario
            producto.cantidad -= item['cantidad']
            producto.save()
        
        mesa.estado = 'OCUPADA'
        mesa.save()
        
        # Notificar cambios en tiempo real
        notificar_cambio_cocina()
        notificar_cambio_stock()
        
        orden_completa = obtener_datos_completos_orden(nueva_orden)
        
        return JsonResponse({
            'success': True, 
            'orden_id': nueva_orden.id,
            'orden_data': orden_completa
        }, status=201)

    except (KeyError, Mesa.DoesNotExist, Producto.DoesNotExist) as e:
        return JsonResponse({'error': f'Datos inválidos: {str(e)}'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
@login_required
@transaction.atomic
@debounce_request(delay=1.0, include_data=True, error_message="⚠️ Modificación en proceso. Espera 1 segundo.")
def api_agregar_productos_orden(request, orden_id):
    """
    API CORREGIDA para agregar productos a una orden existente
    Maneja tanto órdenes normales como órdenes con factura pendiente
    """
    try:
        # 🔧 VALIDACIÓN INICIAL: Verificar que la orden exista
        try:
            orden = Orden.objects.get(id=orden_id)
        except Orden.DoesNotExist:
            return JsonResponse({'error': f'Orden con ID {orden_id} no encontrada'}, status=404)
        
        # 🔧 VALIDACIÓN DE JSON: Manejar errores de parsing JSON
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            return JsonResponse({'error': f'JSON inválido: {str(e)}'}, status=400)
        
        productos_nuevos = data.get('productos', [])
        es_orden_facturada = data.get('es_orden_facturada', False)
        
        print(f"🔥 Procesando {len(productos_nuevos)} productos para orden {orden_id}")
        
        if not productos_nuevos:
            return JsonResponse({'error': 'No hay productos para agregar'}, status=400)
        
        # 🔧 VERIFICAR PERMISOS: Controlar acceso
        if orden.mesero != request.user and not request.user.is_superuser:
            return JsonResponse({'error': 'Solo puedes modificar tus propias órdenes'}, status=403)
              
        # 🔧 VERIFICAR SI LA ORDEN TIENE FACTURA PENDIENTE
        tiene_factura_pendiente = False
        factura = None
        
        try:
            factura = orden.factura
            if factura.estado_pago in ['NO_PAGADA', 'PARCIAL']:
                tiene_factura_pendiente = True
                print(f"💰 Orden {orden_id} tiene factura pendiente ID: {factura.id}")
            else:
                print(f"💳 Orden {orden_id} tiene factura pagada: {factura.estado_pago}")
        except Factura.DoesNotExist:
            print(f"📄 Orden {orden_id} no tiene factura asociada")
        except Exception as e:
            print(f"⚠️ Error verificando factura de orden {orden_id}: {e}")
        
        # 🔧 VALIDAR QUE LA ORDEN PUEDA SER MODIFICADA
        if orden.estado == 'SERVIDA' and not tiene_factura_pendiente:
            return JsonResponse({
                'error': 'No se puede modificar una orden servida con factura pagada'
            }, status=400)
        
        # 🔧 VALIDACIÓN COMPLETA DE PRODUCTOS Y STOCK
        productos_validados = []
        for item in productos_nuevos:
            try:
                # Verificar que existan los campos requeridos
                if 'id' not in item or 'cantidad' not in item:
                    return JsonResponse({
                        'error': 'Faltan campos requeridos en producto: id y cantidad son obligatorios'
                    }, status=400)
                
                producto = Producto.objects.get(
                    id=item['id'], 
                    is_active=True, 
                    is_available=True
                )
                
                try:
                    cantidad_solicitada = int(item['cantidad'])
                except (ValueError, TypeError):
                    return JsonResponse({
                        'error': f'Cantidad inválida para {producto.nombre}: debe ser un número entero'
                    }, status=400)
                
                if cantidad_solicitada <= 0:
                    return JsonResponse({
                        'error': f'Cantidad inválida para {producto.nombre}: debe ser mayor a 0'
                    }, status=400)
                
                if producto.cantidad < cantidad_solicitada:
                    return JsonResponse({
                        'error': f'Stock insuficiente para {producto.nombre}. Disponible: {producto.cantidad}, solicitado: {cantidad_solicitada}'
                    }, status=400)
                
                productos_validados.append({
                    'producto': producto,
                    'cantidad': cantidad_solicitada,
                    'observaciones': item.get('observaciones', '').strip()
                })
                
            except Producto.DoesNotExist:
                return JsonResponse({
                    'error': f'Producto con ID {item.get("id", "desconocido")} no encontrado o inactivo'
                }, status=404)
            except Exception as e:
                return JsonResponse({
                    'error': f'Error procesando producto {item.get("id", "desconocido")}: {str(e)}'
                }, status=400)
        
        if not productos_validados:
            return JsonResponse({'error': 'No hay productos válidos para agregar'}, status=400)
        
        print(f"✅ Validación completada para {len(productos_validados)} productos")
        
        # 🔧 DETERMINAR MARCADOR SEGÚN TIPO DE ORDEN
        if tiene_factura_pendiente or es_orden_facturada:
            marcador_obs = "AGREGADO_POST_FACTURA"
            tipo_agregado = "post-factura"
        else:
            marcador_obs = "AGREGADO_DESPUES"
            tipo_agregado = "después de creación"
        
        print(f"🏷️ Productos serán marcados como: {marcador_obs}")
        
        # 🔧 PROCESAR PRODUCTOS Y ACTUALIZAR STOCK
        productos_agregados = []
        total_agregado = 0
        
        for item_validado in productos_validados:
            try:
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
                subtotal = cantidad * producto.precio
                total_agregado += subtotal
                
                # 🔧 ACTUALIZAR STOCK INMEDIATAMENTE
                stock_anterior = producto.cantidad
                producto.cantidad -= cantidad
                producto.save()
                
                print(f"📦 {producto.nombre}: Stock {stock_anterior} → {producto.cantidad} (-{cantidad})")
                
            except Exception as e:
                print(f"❌ Error procesando {producto.nombre}: {e}")
                return JsonResponse({
                    'error': f'Error interno procesando {producto.nombre}: {str(e)}'
                }, status=500)
        
        print(f"💰 Total agregado: ${total_agregado:,.2f}")
        
        # 🔧 ACTUALIZAR FACTURA SI EXISTE
        nueva_factura_total = None
        if tiene_factura_pendiente and factura:
            try:
                factura_anterior = factura.total
                factura.subtotal += total_agregado
                factura.total += total_agregado
                factura.save()
                nueva_factura_total = float(factura.total)
                print(f"🧾 Factura {factura.id}: ${factura_anterior:,.2f} → ${factura.total:,.2f}")
            except Exception as e:
                print(f"❌ Error actualizando factura: {e}")
                return JsonResponse({
                    'error': f'Error actualizando factura: {str(e)}'
                }, status=500)
        
        # 🔧 ACTUALIZAR ESTADO DE LA ORDEN
        estado_anterior = orden.estado
        try:
            if orden.estado == 'LISTA':
                orden.estado = 'EN_PROCESO'
                orden.listo_en = None
                orden.save()
                print(f"📄 Orden {orden_id}: {estado_anterior} → EN_PROCESO (productos nuevos)")
            elif orden.estado == 'SERVIDA' and tiene_factura_pendiente:
                orden.estado = 'EN_PROCESO'
                orden.save()
                print(f"📄 Orden {orden_id}: SERVIDA → EN_PROCESO (productos post-factura)")
        except Exception as e:
            print(f"❌ Error actualizando estado de orden: {e}")
            return JsonResponse({
                'error': f'Error actualizando estado de orden: {str(e)}'
            }, status=500)
        
        # 🔧 NOTIFICAR CAMBIOS EN TIEMPO REAL
        try:
            notificar_cambio_cocina()
            notificar_cambio_stock()
        except Exception as e:
            print(f"⚠️ Error en notificaciones: {e}")
            # No fallar la operación por esto
        
        # 🔧 PREPARAR RESPUESTA SEGURA
        try:
            orden_completa = obtener_datos_completos_orden(orden)
        except Exception as e:
            print(f"❌ Error obteniendo datos completos: {e}")
            # Crear respuesta mínima en caso de error
            orden_completa = {
                'orden_id': orden.id,
                'estado': orden.estado,
                'mesa': {'numero': orden.mesa.numero},
                'productos': [],
                'total': float(total_agregado)
            }
        
        # Mensaje personalizado según el contexto
        if tiene_factura_pendiente:
            mensaje = f'✅ Se agregaron {len(productos_agregados)} productos a la orden facturada. Total actualizado: ${nueva_factura_total:,.0f}'
        else:
            mensaje = f'✅ Se agregaron {len(productos_agregados)} productos a la orden'
        
        respuesta = {
            'success': True,
            'mensaje': mensaje,
            'productos_agregados': len(productos_agregados),
            'total_agregado': float(total_agregado),
            'tiene_factura_pendiente': tiene_factura_pendiente,
            'tipo_agregado': tipo_agregado,
            'orden_data': orden_completa
        }
        
        if nueva_factura_total is not None:
            respuesta['nueva_factura_total'] = nueva_factura_total
        
        print(f"✅ Respuesta exitosa para orden {orden_id}")
        return JsonResponse(respuesta)
        
    except Exception as e:
        print(f"❌ Error inesperado en api_agregar_productos_orden: {str(e)}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'error': f'Error interno del servidor: {str(e)}'
        }, status=500)


@require_POST
@login_required
@transaction.atomic
def api_agregar_productos_orden_facturada(request, orden_id):
    """API para agregar productos a orden con factura pendiente"""
    try:
        orden = get_object_or_404(Orden, id=orden_id)
        
        # Verificar permisos
        if orden.mesero != request.user and not request.user.is_superuser:
            return JsonResponse({'error': 'Solo puedes modificar tus propias órdenes'}, status=403)
        
        # ✅ CORRECCIÓN: Verificar que tenga factura pendiente con manejo de errores
        try:
            factura = orden.factura
            if factura.estado_pago not in ['NO_PAGADA', 'PARCIAL']:
                return JsonResponse({'error': 'La factura ya está pagada, no se puede modificar'}, status=400)
        except Factura.DoesNotExist:
            return JsonResponse({'error': 'Esta orden no tiene factura asociada'}, status=404)
        except Exception as e:
            print(f"❌ Error verificando factura: {e}")
            return JsonResponse({'error': 'Error verificando el estado de la factura'}, status=500)
        
        data = json.loads(request.body)
        productos_nuevos = data.get('productos', [])
        
        if not productos_nuevos:
            return JsonResponse({'error': 'No hay productos para agregar'}, status=400)
        
        # Validar stock
        for item in productos_nuevos:
            try:
                producto = Producto.objects.get(id=item['id'])
                if producto.cantidad < item['cantidad']:
                    return JsonResponse({'error': f'Stock insuficiente para {producto.nombre}.'}, status=400)
            except Producto.DoesNotExist:
                return JsonResponse({'error': f'Producto con ID {item["id"]} no encontrado'}, status=404)
        
        # Agregar productos nuevos
        productos_agregados = []
        total_agregado = 0
        
        for item in productos_nuevos:
            producto = Producto.objects.get(id=item['id'])
            
            # Marcar como agregado post-factura
            obs_producto = item.get('observaciones', '')
            if obs_producto:
                obs_final = f"AGREGADO_POST_FACTURA|{obs_producto}"
            else:
                obs_final = "AGREGADO_POST_FACTURA"
            
            nuevo_producto_orden = OrdenProducto.objects.create(
                orden=orden,
                producto=producto,
                cantidad=item['cantidad'],
                precio_unitario=producto.precio,
                observaciones=obs_final,
                estado='PENDIENTE'
            )
            
            productos_agregados.append(nuevo_producto_orden)
            total_agregado += item['cantidad'] * producto.precio
            
            # Descontar stock
            producto.cantidad -= item['cantidad']
            producto.save()
        
        # Actualizar la factura existente
        factura.subtotal += total_agregado
        factura.total += total_agregado
        factura.save()
        
        # Volver a poner la orden EN_PROCESO porque hay productos nuevos
        orden.estado = 'EN_PROCESO'
        orden.listo_en = None
        orden.save()
        
        # Notificar cambios
        notificar_cambio_cocina()
        notificar_cambio_stock()
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Se agregaron {len(productos_nuevos)} productos a la orden facturada. Total actualizado: ${factura.total:,.0f}',
            'productos_agregados': len(productos_agregados),
            'total_agregado': float(total_agregado),
            'nueva_factura_total': float(factura.total),
            'orden_data': obtener_datos_completos_orden(orden)
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Formato JSON inválido'}, status=400)
    except Exception as e:
        print(f"❌ Error en api_agregar_productos_orden_facturada: {str(e)}")
        return JsonResponse({'error': f'Error interno: {str(e)}'}, status=500)


@login_required
def api_get_orden_por_mesa(request, mesa_id):
    """API para obtener la orden activa de una mesa específica (CORREGIDA)"""
    try:
        mesa = get_object_or_404(Mesa, id=mesa_id)
        
        # ✅ LÓGICA MEJORADA: Buscar orden activa O servida con factura no pagada
        orden = Orden.objects.filter(
            Q(mesa=mesa) & 
            (Q(estado__in=['EN_PROCESO', 'LISTA', 'NUEVA']) | 
             Q(estado='SERVIDA', factura__estado_pago__in=['NO_PAGADA', 'PARCIAL']))
        ).distinct().first()
        
        if not orden:
            return JsonResponse({'error': 'No hay orden activa o con pago pendiente en esta mesa'}, status=404)
        
        orden_data = obtener_datos_completos_orden(orden)
        
        # ✅ AÑADIR FLAG: Informar a la interfaz si tiene factura pendiente
        tiene_factura_pendiente = False
        if hasattr(orden, 'factura'):
            if orden.factura.estado_pago in ['NO_PAGADA', 'PARCIAL']:
                tiene_factura_pendiente = True

        orden_data['tiene_factura_pendiente'] = tiene_factura_pendiente
        
        # Lógica existente para separar productos...
        productos_originales = []
        productos_agregados = []
        
        for producto in orden_data['productos']:
            op = OrdenProducto.objects.get(id=producto['id'])
            if op.observaciones and ('AGREGADO_DESPUES' in op.observaciones or 'AGREGADO_POST_FACTURA' in op.observaciones):
                producto['agregado_despues'] = True
                productos_agregados.append(producto)
            else:
                producto['agregado_despues'] = False
                productos_originales.append(producto)
        
        orden_data['productos_originales'] = productos_originales
        orden_data['productos_agregados'] = productos_agregados
        
        return JsonResponse(orden_data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
@login_required
@transaction.atomic
@debounce_request(delay=1.2, critical=True, error_message="⚠️ Orden siendo servida. Espera antes de marcar otra.")
def api_marcar_orden_servida(request, orden_id):
    """API para marcar una orden completa como servida"""
    try:
        orden = get_object_or_404(Orden, id=orden_id)
        
        if orden.estado != 'LISTA':
            return JsonResponse({
                'error': f'La orden debe estar en estado LISTA. Estado actual: {orden.estado}'
            }, status=400)
        
        productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
        if productos_pendientes > 0:
            return JsonResponse({
                'error': f'Aún hay {productos_pendientes} productos pendientes en esta orden'
            }, status=400)
        
        # Marcar como servida
        orden.estado = 'SERVIDA'
        orden.save()
        
        # Liberar la mesa
        mesa = orden.mesa
        mesa.estado = 'LIBRE'
        mesa.save()
        
        # Notificar cambios
        notificar_cambio_cocina()
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Orden #{orden_id} servida exitosamente',
            'mesa': mesa.numero,
            'orden_id': orden_id
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# === API MESERO ===

@login_required
def api_get_ordenes_mesero(request):
    """API para obtener órdenes que debe monitorear el mesero"""
    try:
        # Órdenes del mesero que están activas
        ordenes = Orden.objects.filter(
            mesero=request.user,
            estado__in=['EN_PROCESO', 'LISTA']
        ).order_by('-creado_en')
        
        ordenes_data = []
        for orden in ordenes:
            orden_data = obtener_datos_completos_orden(orden)
            
            # Contar productos por estado
            productos_listos = orden.productos_ordenados.filter(estado='LISTO').count()
            productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
            
            # Verificar si hay productos agregados después
            productos_agregados = orden.productos_ordenados.filter(
                observaciones__icontains='AGREGADO_DESPUES'
            ).count()
            
            # Agregar información adicional para meseros
            orden_data.update({
                'tiene_productos_listos': productos_listos > 0,
                'productos_listos_count': productos_listos,
                'productos_pendientes_count': productos_pendientes,
                'productos_agregados_count': productos_agregados,
                'necesita_atencion': productos_listos > 0,  # Si hay productos listos, necesita atención
            })
            
            ordenes_data.append(orden_data)
        
        return JsonResponse(ordenes_data, safe=False)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def api_get_todas_ordenes_mesero(request):
    """API mejorada para obtener todas las órdenes del mesero incluyendo domicilios y reservas"""
    try:
        # Obtener filtro desde query params
        filtro = request.GET.get('filtro', 'todas')
        
        # Base query para órdenes del mesero
        ordenes_query = Orden.objects.filter(mesero=request.user)
        
        # Aplicar filtros mejorados
        if filtro == 'activas':
            ordenes_query = ordenes_query.filter(estado__in=['EN_PROCESO', 'LISTA'])
        elif filtro == 'servidas':
            ordenes_query = ordenes_query.filter(estado='SERVIDA').filter(
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
        elif filtro == 'domicilios':  # ✅ NUEVO FILTRO
            ordenes_query = ordenes_query.filter(mesa__numero=0)
        elif filtro == 'reservas':   # ✅ NUEVO FILTRO
            ordenes_query = ordenes_query.filter(mesa__numero=50)
        
        # Ordenar por fecha y limitar
        if filtro == 'todas':
            from datetime import timedelta
            fecha_limite = timezone.now() - timedelta(days=7)
            ordenes_query = ordenes_query.filter(creado_en__gte=fecha_limite)
            
        ordenes = ordenes_query.order_by('-creado_en')[:50]
        
        ordenes_data = []
        for orden in ordenes:
            orden_data = obtener_datos_completos_orden(orden)
            
            # Determinar tipo de orden
            es_domicilio = orden.mesa.numero == 0
            es_reserva = orden.mesa.numero == 50
            
            # Extraer información del cliente según el tipo
            cliente_info = {}
            if es_domicilio:
                cliente_info = extraer_info_cliente_domicilio(orden.observaciones)
            elif es_reserva:
                cliente_info = extraer_info_cliente_reserva(orden.observaciones)
            
            # Contar productos por estado
            productos_listos = orden.productos_ordenados.filter(estado='LISTO').count()
            productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
            productos_agregados = orden.productos_ordenados.filter(
                observaciones__icontains='AGREGADO_DESPUES'
            ).count()
            productos_post_factura = orden.productos_ordenados.filter(
                observaciones__icontains='AGREGADO_POST_FACTURA'
            ).count()
            
            # Marcar productos con información especial
            productos_con_info = []
            for po in orden.productos_ordenados.all():
                agregado_despues = po.observaciones and 'AGREGADO_DESPUES' in po.observaciones
                agregado_post_factura = po.observaciones and 'AGREGADO_POST_FACTURA' in po.observaciones
                
                # Limpiar observaciones para mostrar
                obs_limpia = ''
                if po.observaciones:
                    if 'AGREGADO_POST_FACTURA' in po.observaciones:
                        parts = po.observaciones.split('|')
                        obs_limpia = parts[1] if len(parts) > 1 else ''
                    elif 'AGREGADO_DESPUES' in po.observaciones:
                        parts = po.observaciones.split('|')
                        obs_limpia = parts[1] if len(parts) > 1 else ''
                    else:
                        obs_limpia = po.observaciones
                
                productos_con_info.append({
                    'id': po.id,
                    'nombre': po.producto.nombre,
                    'cantidad': po.cantidad,
                    'precio_unitario': float(po.precio_unitario),
                    'observaciones': obs_limpia,
                    'estado': po.estado,
                    'listo_en': po.listo_en.isoformat() if po.listo_en else None,
                    'agregado_despues': agregado_despues,
                    'agregado_post_factura': agregado_post_factura
                })
            
            # Reemplazar productos en orden_data
            orden_data['productos'] = productos_con_info
            
            # Determinar estados especiales
            tiene_factura_pendiente = False
            factura_info = None
            
            try:
                factura = orden.factura
                if factura.estado_pago in ['NO_PAGADA', 'PARCIAL']:
                    tiene_factura_pendiente = True
                    factura_info = {
                        'id': factura.id,
                        'numero': factura.numero_factura or f"FAC-{factura.id}",
                        'total': float(factura.total),
                        'estado_pago': factura.estado_pago,
                        'metodo_pago': factura.metodo_pago
                    }
            except:
                pass
            
            # ✅ AGREGAR INFORMACIÓN DE CLIENTE
            orden_data.update({
                'tiene_productos_listos': productos_listos > 0,
                'productos_listos_count': productos_listos,
                'productos_pendientes_count': productos_pendientes,
                'productos_agregados_count': productos_agregados,
                'productos_post_factura_count': productos_post_factura,
                'necesita_atencion': productos_listos > 0 and orden.estado != 'SERVIDA',
                'puede_marcar_lista': productos_pendientes == 0 and orden.estado == 'EN_PROCESO',
                'puede_entregar': orden.estado == 'LISTA',
                'puede_modificar': orden.estado != 'SERVIDA' or tiene_factura_pendiente,
                'tiene_factura_pendiente': tiene_factura_pendiente,
                'factura_info': factura_info,
                'es_domicilio': es_domicilio,
                'es_reserva': es_reserva,
                'cliente_info': cliente_info,  # ✅ NUEVA INFORMACIÓN
                'tiempo_transcurrido': calcular_tiempo_transcurrido(orden.creado_en),
            })
            
            ordenes_data.append(orden_data)
        
        return JsonResponse(ordenes_data, safe=False)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
@login_required
@transaction.atomic
@debounce_request(delay=1, critical=True, error_message="⚠️ Acción muy rápida. Espera antes de marcar otra.")
def api_marcar_orden_lista_manual(request, orden_id):
    """API para que el mesero marque manualmente una orden como lista"""
    try:
        orden = get_object_or_404(Orden, id=orden_id)
        
        # Verificar que sea el mesero de la orden
        if orden.mesero != request.user and not request.user.is_superuser:
            return JsonResponse({'error': 'Solo puedes marcar como lista tus propias órdenes'}, status=403)
        
        if orden.estado == 'LISTA':
            return JsonResponse({'error': 'La orden ya está marcada como lista'}, status=400)
        
        if orden.estado == 'SERVIDA':
            return JsonResponse({'error': 'No se puede modificar una orden ya servida'}, status=400)
        
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
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Orden #{orden_id} marcada como lista exitosamente',
            'productos_actualizados': productos_actualizados,
            'orden_data': obtener_datos_completos_orden(orden)
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
@login_required
@debounce_request(delay=1.5, critical=True, error_message="⚠️ Entrega en proceso. Espera antes de marcar otra.")
@transaction.atomic
def api_marcar_orden_entregada(request, orden_id):
    """API para marcar una orden como entregada y generar factura"""
    try:
        orden = get_object_or_404(Orden, id=orden_id)
        
        # Verificar que sea el mesero de la orden
        if orden.mesero != request.user:
            return JsonResponse({'error': 'Solo puedes entregar tus propias órdenes'}, status=403)
        
        if orden.estado != 'LISTA':
            return JsonResponse({
                'error': f'La orden debe estar LISTA para entregarla. Estado actual: {orden.estado}'
            }, status=400)
        
        # Verificar que todos los productos estén listos
        productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
        if productos_pendientes > 0:
            return JsonResponse({
                'error': f'Aún hay {productos_pendientes} productos pendientes'
            }, status=400)
        
        # Calcular total
        total_orden = calcular_total_orden(orden)
        
        # Marcar como servida
        orden.estado = 'SERVIDA'
        orden.save()
        
        # Liberar la mesa
        mesa = orden.mesa
        mesa.estado = 'LIBRE'
        mesa.save()
        
        # ✅ CORREGIDO: Gestionar factura sin duplicados
        try:
            # Intentar obtener factura existente
            factura = Factura.objects.get(orden=orden)
            # Si existe, actualizar estado a NO_PAGADA
            factura.estado_pago = 'NO_PAGADA'
            factura.subtotal = total_orden
            factura.total = total_orden
            factura.save()
            print(f"✅ Factura existente actualizada para orden {orden_id}")
            
        except Factura.DoesNotExist:
            # Si no existe, crear nueva
            factura = Factura.objects.create(
                orden=orden,
                subtotal=total_orden,
                total=total_orden,
                estado_pago='NO_PAGADA'
            )
            print(f"✅ Nueva factura creada para orden {orden_id}")
        
        # Notificar cambios
        notificar_cambio_cocina()
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Orden #{orden_id} entregada exitosamente',
            'factura_id': factura.id,
            'mesa': mesa.numero,
            'total': float(total_orden)
        })
        
    except Exception as e:
        print(f"❌ Error en api_marcar_orden_entregada: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def api_get_mesas_ocupadas(request):
    """API mejorada para obtener mesas ocupadas incluyendo órdenes de domicilio"""
    try:
        # ✅ CORRECCIÓN: Cambiar __ne por exclude() y usar __in
        # Obtener mesas físicas ocupadas (excluyendo mesas de domicilio 0 y 50)
        mesas_fisicas_ocupadas = Mesa.objects.filter(
            is_active=True,
            estado='OCUPADA'
        ).exclude(
            numero__in=[0, 50]  # ✅ Usar exclude() con __in en lugar de __ne
        )
        
        # Obtener mesas de domicilio (0 y 50) - siempre disponibles
        mesas_domicilio = Mesa.objects.filter(
            is_active=True,
            numero__in=[0, 50]
        )
        
        mesas_data = []
        
        # === PROCESAR MESAS FÍSICAS OCUPADAS ===
        for mesa in mesas_fisicas_ocupadas:
            # Obtener la orden activa de la mesa
            orden = Orden.objects.filter(
                mesa=mesa,
                estado__in=['EN_PROCESO', 'LISTA', 'NUEVA']
            ).first()
            
            productos_count = 0
            if orden:
                productos_count = orden.productos_ordenados.count()
            
            mesas_data.append({
                'id': mesa.id,
                'numero': mesa.numero,
                'ubicacion': mesa.ubicacion,
                'capacidad': mesa.capacidad,
                'productos_count': productos_count,
                'tiene_orden': orden is not None,
                'orden_id': orden.id if orden else None,
                'es_domicilio': False,
                'ordenes_count': 1 if orden else 0
            })
        
        # === PROCESAR MESAS DE DOMICILIO (0 y 50) ===
        for mesa_domicilio in mesas_domicilio:
            # Obtener TODAS las órdenes activas y no pagadas de domicilio
            ordenes_activas = Orden.objects.filter(
                mesa=mesa_domicilio,
                estado__in=['EN_PROCESO', 'LISTA', 'NUEVA']
            )
            
            # También incluir órdenes servidas pero no pagadas (factura pendiente)
            try:
                # ✅ MANEJO SEGURO: Verificar si existe la relación factura
                ordenes_no_pagadas = Orden.objects.filter(
                    mesa=mesa_domicilio,
                    estado='SERVIDA'
                ).filter(
                    factura__estado_pago__in=['NO_PAGADA', 'PARCIAL']
                )
            except Exception as e:
                print(f"⚠️ Error obteniendo órdenes no pagadas: {e}")
                ordenes_no_pagadas = Orden.objects.none()  # QuerySet vacío
            
            # Combinar ambos tipos de órdenes usando union
            try:
                todas_las_ordenes = ordenes_activas.union(ordenes_no_pagadas)
            except Exception as e:
                print(f"⚠️ Error en union, usando solo órdenes activas: {e}")
                todas_las_ordenes = ordenes_activas
            
            # Si hay órdenes, crear una entrada por cada orden O una entrada general
            if todas_las_ordenes.exists():
                # OPCIÓN 1: Mostrar como una sola mesa con múltiples órdenes
                orden_principal = todas_las_ordenes.first()
                total_productos = sum(orden.productos_ordenados.count() for orden in todas_las_ordenes)
                
                mesas_data.append({
                    'id': mesa_domicilio.id,
                    'numero': mesa_domicilio.numero,
                    'ubicacion': 'Domicilio',
                    'capacidad': 999,  # Capacidad ilimitada para domicilio
                    'productos_count': total_productos,
                    'tiene_orden': True,
                    'orden_id': orden_principal.id,
                    'es_domicilio': True,
                    'ordenes_count': todas_las_ordenes.count(),
                    'ordenes_multiples': True  # ✅ Nuevo campo para indicar múltiples órdenes
                })
            else:
                # Si no hay órdenes, aún mostrar la mesa de domicilio como disponible
                mesas_data.append({
                    'id': mesa_domicilio.id,
                    'numero': mesa_domicilio.numero,
                    'ubicacion': 'Domicilio',
                    'capacidad': 999,
                    'productos_count': 0,
                    'tiene_orden': False,
                    'orden_id': None,
                    'es_domicilio': True,
                    'ordenes_count': 0,
                    'ordenes_multiples': False
                })
        
        return JsonResponse(mesas_data, safe=False)
        
    except Exception as e:
        print(f"❌ Error en api_get_mesas_ocupadas: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def api_get_mesas_ocupadas_detallado(request):
    """Versión alternativa que muestra cada orden de domicilio por separado"""
    try:
        mesas_data = []
        
        # === MESAS FÍSICAS OCUPADAS ===
        # ✅ CORRECCIÓN: Usar exclude() en lugar de __ne
        mesas_fisicas_ocupadas = Mesa.objects.filter(
            is_active=True,
            estado='OCUPADA'
        ).exclude(
            numero__in=[0, 50]  # ✅ Cambio principal aquí
        )
        
        for mesa in mesas_fisicas_ocupadas:
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
                    'ordenes_count': 1
                })
        
        # === MESAS DE DOMICILIO - CADA ORDEN POR SEPARADO ===
        mesas_domicilio = Mesa.objects.filter(
            is_active=True,
            numero__in=[0, 50]
        )
        
        for mesa_domicilio in mesas_domicilio:
            # Obtener todas las órdenes de domicilio
            ordenes_activas = Orden.objects.filter(
                mesa=mesa_domicilio,
                estado__in=['EN_PROCESO', 'LISTA', 'NUEVA']
            )
            
            try:
                ordenes_no_pagadas = Orden.objects.filter(
                    mesa=mesa_domicilio,
                    estado='SERVIDA'
                ).filter(
                    factura__estado_pago__in=['NO_PAGADA', 'PARCIAL']
                )
            except Exception:
                ordenes_no_pagadas = Orden.objects.none()
            
            try:
                todas_las_ordenes = ordenes_activas.union(ordenes_no_pagadas)
            except Exception:
                todas_las_ordenes = ordenes_activas
            
            # Crear una entrada por cada orden
            for i, orden in enumerate(todas_las_ordenes):
                # Extraer información del cliente de las observaciones
                if mesa_domicilio.numero == 0:
                    cliente_info = extraer_info_cliente_domicilio(orden.observaciones)
                    tipo_descripcion = 'Domicilio'
                    icono = '🏠'
                else:
                    cliente_info = extraer_info_cliente_reserva(orden.observaciones)
                    tipo_descripcion = 'Reserva'
                    icono = '📅'
                
                mesas_data.append({
                    'id': f"{tipo_descripcion.lower()}-{orden.id}",  # ID único para domicilio/reserva
                    'numero': f"{icono} {tipo_descripcion[0]}{i+1}",  # Ej: "🏠 D1", "📅 R1"
                    'ubicacion': f'{tipo_descripcion} #{i+1}',
                    'capacidad': 999,
                    'productos_count': orden.productos_ordenados.count(),
                    'tiene_orden': True,
                    'orden_id': orden.id,
                    'es_domicilio': mesa_domicilio.numero == 0,
                    'es_reserva': mesa_domicilio.numero == 50,
                    'ordenes_count': 1,
                    'mesa_real_id': mesa_domicilio.id,  # ✅ ID real de la mesa para referencias
                    'cliente_nombre': cliente_info.get('nombre'),
                    'direccion': cliente_info.get('direccion') if mesa_domicilio.numero == 0 else None,
                    'telefono': cliente_info.get('telefono')
                })
            
            # Si no hay órdenes, mostrar mesa domicilio disponible
            if not todas_las_ordenes.exists():
                tipo_descripcion = 'Domicilio' if mesa_domicilio.numero == 0 else 'Reserva'
                mesas_data.append({
                    'id': mesa_domicilio.id,
                    'numero': mesa_domicilio.numero,
                    'ubicacion': f'{tipo_descripcion} (Disponible)',
                    'capacidad': 999,
                    'productos_count': 0,
                    'tiene_orden': False,
                    'orden_id': None,
                    'es_domicilio': mesa_domicilio.numero == 0,
                    'es_reserva': mesa_domicilio.numero == 50,
                    'ordenes_count': 0
                })
        
        return JsonResponse(mesas_data, safe=False)
        
    except Exception as e:
        print(f"❌ Error en api_get_mesas_ocupadas_detallado: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# === API COCINA ===
@login_required
def api_get_ordenes_cocina(request):
    """
    API que devuelve las órdenes activas para cocina - CORREGIDA
    
    🔧 CORRECCIÓN PRINCIPAL: Las reservas (mesa 50) NO aparecen en órdenes normales de cocina
    Las reservas son para fechas futuras y se ven solo en modal especial
    """
    try:
        # 🔧 CORRECCIÓN: Excluir reservas (mesa 50) de las órdenes normales de cocina
        # Las reservas solo se preparan cuando es su fecha/hora programada
        ordenes = Orden.objects.filter(
            estado__in=['EN_PROCESO', 'NUEVA', 'LISTA']
        ).exclude(
            mesa__numero=50  # ✅ EXCLUIR RESERVAS
        ).order_by('creado_en')
        
        lista_ordenes = []
        for orden in ordenes:
            try:
                productos_ordenados = orden.productos_ordenados.all()
                lista_productos = []
                
                todos_listos = True
                for po in productos_ordenados:
                    if po.estado == 'PENDIENTE':
                        todos_listos = False
                    
                    # Detectar productos agregados después usando observaciones
                    agregado_despues = po.observaciones and 'AGREGADO_DESPUES' in po.observaciones
                    
                    # Limpiar observaciones para mostrar
                    obs_limpia = ''
                    if po.observaciones:
                        if 'AGREGADO_DESPUES' in po.observaciones:
                            parts = po.observaciones.split('|')
                            if len(parts) > 1:
                                obs_limpia = parts[1]  # Obtener la observación real después del marcador
                        else:
                            obs_limpia = po.observaciones
                    
                    lista_productos.append({
                        'id': po.id,
                        'nombre': po.producto.nombre,
                        'cantidad': po.cantidad,
                        'observaciones': obs_limpia,
                        'estado': po.estado,
                        'agregado_despues': agregado_despues,
                        'clase_css': 'nuevo-agregado' if agregado_despues else ('listo' if po.estado == 'LISTO' else '')
                    })
                
                # 🔧 CORRECCIÓN: Formato consistente de fecha y observaciones completas
                orden_data = {
                    'id': orden.id,
                    'mesa': orden.mesa.numero,
                    'mesero': orden.mesero.nombre,
                    'creado_en': orden.creado_en.isoformat(),  # ✅ Formato ISO consistente
                    'observaciones': orden.observaciones if orden.observaciones else '',  # ✅ Observaciones completas
                    'productos': lista_productos,
                    'completada': todos_listos or orden.estado == 'LISTA',
                    'tiene_agregados': any(p['agregado_despues'] for p in lista_productos)
                }
                
                lista_ordenes.append(orden_data)
                
            except Exception as e:
                print(f"ERROR procesando orden {orden.id}: {str(e)}")
                continue
        
        print(f"📊 Órdenes enviadas a cocina: {len(lista_ordenes)} (sin incluir reservas)")
        return JsonResponse(lista_ordenes, safe=False)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# === AGREGAR ESTA FUNCIÓN AL FINAL DE core/views/api_views.py ===
# No cambies nada más, solo agrega esta función

@login_required
def api_get_reservas_cocina(request):
    """API específica para obtener solo las reservas (mesa 50) para planificación"""
    try:
        # Solo reservas (mesa 50)
        reservas = Orden.objects.filter(
            mesa__numero=50,
            estado__in=['EN_PROCESO', 'NUEVA', 'LISTA', 'SERVIDA']
        ).order_by('creado_en')
        
        lista_reservas = []
        for orden in reservas:
            try:
                productos_ordenados = orden.productos_ordenados.all()
                lista_productos = []
                
                todos_listos = True
                for po in productos_ordenados:
                    if po.estado == 'PENDIENTE':
                        todos_listos = False
                    
                    agregado_despues = po.observaciones and 'AGREGADO_DESPUES' in po.observaciones
                    
                    obs_limpia = ''
                    if po.observaciones:
                        if 'AGREGADO_DESPUES' in po.observaciones:
                            parts = po.observaciones.split('|')
                            obs_limpia = parts[1] if len(parts) > 1 else ''
                        else:
                            obs_limpia = po.observaciones
                    
                    lista_productos.append({
                        'id': po.id,
                        'nombre': po.producto.nombre,
                        'cantidad': po.cantidad,
                        'observaciones': obs_limpia,
                        'estado': po.estado,
                        'agregado_despues': agregado_despues
                    })
                
                orden_data = {
                    'id': orden.id,
                    'mesa': orden.mesa.numero,
                    'mesero': orden.mesero.nombre,
                    'creado_en': orden.creado_en.strftime('%I:%M %p'),
                    'observaciones': orden.observaciones if orden.observaciones else '',
                    'productos': lista_productos,
                    'completada': todos_listos or orden.estado == 'LISTA',
                    'estado': orden.estado,
                    'es_reserva': True
                }
                
                lista_reservas.append(orden_data)
                
            except Exception as e:
                print(f"ERROR procesando reserva {orden.id}: {str(e)}")
                continue
        
        print(f"📅 Reservas encontradas: {len(lista_reservas)}")
        return JsonResponse(lista_reservas, safe=False)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_POST
@login_required
@debounce_request(delay=0.8, error_message="⚠️ Acción muy rápida. Espera un momento.")
def api_marcar_producto_listo_tiempo_real(request, producto_orden_id):
    """Marcar producto como listo CON notificación en tiempo real"""
    try:
        producto_orden = get_object_or_404(OrdenProducto, id=producto_orden_id)
        
        if producto_orden.estado == 'LISTO':
            return JsonResponse({'error': 'El producto ya está marcado como listo'}, status=400)
        
        orden = producto_orden.orden
        producto_nombre = producto_orden.producto.nombre
        
        # Actualizar estado
        producto_orden.estado = 'LISTO'
        producto_orden.listo_en = timezone.now()
        producto_orden.save()

        # Verificar si la orden está completa
        productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
        orden_completa = False
        
        if productos_pendientes == 0:
            orden.estado = 'LISTA'
            orden.listo_en = timezone.now()
            orden.save()
            orden_completa = True
        
        # Notificar cambios
        notificar_cambio_cocina()
        
        orden_data = obtener_datos_completos_orden(orden)
        
        response_data = {
            'success': True,
            'producto_listo': True,
            'producto_nombre': producto_nombre,
            'orden_completa': orden_completa,
            'productos_restantes': productos_pendientes,
            'orden_data': orden_data
        }
        ordenes = Orden.objects.filter(
            estado__in=['EN_PROCESO', 'NUEVA', 'LISTA']
        ).exclude(
            mesa__numero=50  # ✅ EXCLUIR RESERVAS
        ).order_by('creado_en')
        
        if orden_completa:
            response_data['mensaje'] = f'¡Orden #{orden.id} completa y lista para servir!'
        else:
            response_data['mensaje'] = f'Producto {producto_nombre} completado. Faltan {productos_pendientes} productos.'
            
        return JsonResponse(response_data)
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
@login_required
@transaction.atomic
@debounce_request(delay=0.8, error_message="⚠️ Acción muy rápida. Espera un momento.")
def api_decrementar_producto_tiempo_real(request, producto_orden_id):
    """
    LÓGICA CORREGIDA: Decrementar significa que el cocinero YA ENTREGÓ una unidad,
    pero el producto se mantiene en estado PENDIENTE hasta completar todas las unidades.
    Solo cuando se entreguen TODAS las unidades, el producto pasa a LISTO automáticamente.
    """
    try:
        producto_orden = get_object_or_404(OrdenProducto, id=producto_orden_id)
        orden = producto_orden.orden
        
        if orden.estado not in ['EN_PROCESO', 'NUEVA']:
            return JsonResponse({
                'error': f'No se puede modificar orden con estado: {orden.estado}'
            }, status=400)
        
        if producto_orden.estado == 'LISTO':
            return JsonResponse({
                'error': 'No se puede decrementar un producto ya completado'
            }, status=400)
        
        if producto_orden.cantidad <= 1:
            return JsonResponse({
                'error': 'No se puede decrementar: solo queda 1 unidad. Usa "Marcar Listo" para completar.'
            }, status=400)
        
        producto_nombre = producto_orden.producto.nombre
        cantidad_original = producto_orden.cantidad
        
        # LÓGICA CORREGIDA: Solo decrementar cantidad, mantener en PENDIENTE
        producto_orden.cantidad -= 1
        producto_orden.save()
        
        # Devolver 1 unidad al inventario
        producto = producto_orden.producto
        producto.cantidad += 1
        producto.save()
        
        # Verificar si quedan productos pendientes en la orden
        productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
        
        mensaje = f'{producto_nombre} decrementado: queda {producto_orden.cantidad} por preparar (entregaste 1 de {cantidad_original})'
        
        # Notificar cambios en tiempo real
        notificar_cambio_cocina()
        notificar_cambio_stock()
        
        return JsonResponse({
            'success': True,
            'nueva_cantidad': producto_orden.cantidad,
            'cantidad_entregada': cantidad_original - producto_orden.cantidad,
            'producto_sigue_pendiente': True,  # Siempre sigue pendiente hasta completar todo
            'mensaje': mensaje,
            'productos_pendientes_restantes': productos_pendientes,
            'orden_data': obtener_datos_completos_orden(orden)
        })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# === API FACTURAS ===

@login_required
def api_get_factura_por_orden(request, orden_id):
    """API para obtener la factura de una orden específica"""
    try:
        orden = get_object_or_404(Orden, id=orden_id)
        
        # Verificar que sea del mesero o admin
        if orden.mesero != request.user and not request.user.is_superuser:
            return JsonResponse({'error': 'No tienes permisos para ver esta factura'}, status=403)
        
        # Buscar factura asociada
        try:
            factura = Factura.objects.get(orden=orden)
        except Factura.DoesNotExist:
            return JsonResponse({'error': 'No se encontró factura para esta orden'}, status=404)
        
        # Obtener productos de la orden
        productos_factura = []
        for producto_orden in orden.productos_ordenados.all():
            subtotal = producto_orden.cantidad * producto_orden.precio_unitario
            
            # Limpiar observaciones
            obs_limpia = ''
            if producto_orden.observaciones:
                if 'AGREGADO_DESPUES' in producto_orden.observaciones:
                    parts = producto_orden.observaciones.split('|')
                    obs_limpia = parts[1] if len(parts) > 1 else ''
                else:
                    obs_limpia = producto_orden.observaciones
            
            productos_factura.append({
                'nombre': producto_orden.producto.nombre,
                'cantidad': producto_orden.cantidad,
                'precio_unitario': float(producto_orden.precio_unitario),
                'subtotal': float(subtotal),
                'observaciones': obs_limpia
            })
        
        factura_data = {
            'id': factura.id,
            'numero_factura': factura.numero_factura or f"FAC-{factura.id}",
            'orden': {
                'id': orden.id,
                'numero_orden': orden.numero_orden,
                'mesa': {
                    'numero': orden.mesa.numero,
                    'ubicacion': orden.mesa.ubicacion,
                    'capacidad': orden.mesa.capacidad
                },
                'mesero': {
                    'nombre': orden.mesero.nombre,
                    'email': orden.mesero.email
                },
                'estado': orden.estado,
                'observaciones': orden.observaciones,
                'creado_en': orden.creado_en.isoformat(),
            },
            'productos': productos_factura,
            'subtotal': float(factura.subtotal),
            'impuesto': float(factura.impuesto),
            'descuento': float(factura.descuento),
            'total': float(factura.total),
            'estado_pago': factura.estado_pago,
            'metodo_pago': factura.metodo_pago,
            'cliente_nombre': factura.cliente_nombre,
            'cliente_identificacion': factura.cliente_identificacion,
            'cliente_telefono': factura.cliente_telefono,
            'observaciones': factura.observaciones,
            'creado_en': factura.creado_en.isoformat(),
            'pagado_en': factura.pagado_en.isoformat() if factura.pagado_en else None,
        }
        
        return JsonResponse(factura_data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# === LONG POLLING (TIEMPO REAL) ===

@never_cache
@login_required
def api_longpolling_cocina(request):
    """Long polling para el dashboard de cocina"""
    hash_anterior = request.GET.get('hash', None)
    
    try:
        resultado = long_polling_cocina(hash_anterior, timeout=25)
        return JsonResponse(resultado)
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'cambios': False,
            'timestamp': timezone.now().isoformat()
        }, status=500)


@never_cache
@login_required  
def api_longpolling_meseros(request):
    """Long polling para meseros - detecta cuando hay productos listos"""
    hash_stock_anterior = request.GET.get('hash_stock', None)
    
    try:
        resultado = long_polling_meseros(hash_stock_anterior, timeout=25)
        
        # Agregar información específica para meseros sobre productos listos
        if resultado.get('cambios'):
            # Obtener órdenes del mesero con productos listos
            ordenes_mesero = Orden.objects.filter(
                mesero=request.user,
                estado__in=['EN_PROCESO', 'LISTA']
            )
            
            notificaciones = []
            for orden in ordenes_mesero:
                productos_listos = orden.productos_ordenados.filter(estado='LISTO')
                if productos_listos.exists():
                    notificaciones.append({
                        'orden_id': orden.id,
                        'mesa': orden.mesa.numero,
                        'productos_listos': [p.producto.nombre for p in productos_listos],
                        'todos_listos': orden.estado == 'LISTA'
                    })
            
            resultado['notificaciones_mesero'] = notificaciones
        
        return JsonResponse(resultado)
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'cambios': False,
            'timestamp': timezone.now().isoformat()
        }, status=500)


# === SISTEMA Y DEBUG ===

@login_required
def api_estadisticas_sistema(request):
    """Endpoint para debugging del sistema de long polling"""
    stats = obtener_estadisticas_sistema()
    return JsonResponse(stats)


@login_required
def api_debug_debounce_status(request):
    """Vista de debugging para ver el estado de debounce del usuario"""
    try:
        from django.core.cache import cache
        from ..decorators import DEBOUNCE_CONFIG
        
        user_id = request.user.id
        acciones_comunes = [
            'api_crear_orden_tiempo_real',
            'api_agregar_productos_orden', 
            'api_marcar_orden_entregada',
            'api_marcar_producto_listo_tiempo_real'
        ]
        
        estado_debounces = {}
        current_time = time.time()
        
        for accion in acciones_comunes:
            debounce_key = f"{DEBOUNCE_CONFIG['CACHE_PREFIX']}{user_id}:{accion}"
            last_request_time = cache.get(debounce_key)
            
            if last_request_time:
                tiempo_restante = max(0, DEBOUNCE_CONFIG['DEFAULT_DELAY'] - (current_time - last_request_time))
                estado_debounces[accion] = {
                    'bloqueado': tiempo_restante > 0,
                    'tiempo_restante': tiempo_restante,
                    'ultimo_uso': last_request_time
                }
            else:
                estado_debounces[accion] = {
                    'bloqueado': False,
                    'tiempo_restante': 0,
                    'ultimo_uso': None
                }
        
        return JsonResponse({
            'user_id': user_id,
            'timestamp_actual': current_time,
            'debounces': estado_debounces
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    

@require_POST
@login_required
@transaction.atomic
@debounce_request(delay=1.0, error_message="⚠️ Procesando pago. Espera un momento.")
def api_marcar_factura_pagada(request, factura_id):
    """API para marcar una factura como pagada"""
    try:
        factura = get_object_or_404(Factura, id=factura_id)
        
        # Verificar permisos
        if factura.orden.mesero != request.user and not request.user.is_superuser:
            return JsonResponse({'error': 'No tienes permisos para modificar esta factura'}, status=403)
        
        # Verificar que la factura no esté ya pagada
        if factura.estado_pago == 'PAGADA':
            return JsonResponse({'error': 'La factura ya está marcada como pagada'}, status=400)
        
        # Obtener datos del request
        data = json.loads(request.body)
        metodo_pago = data.get('metodo_pago', '').strip()
        cliente_nombre = data.get('cliente_nombre', '').strip()
        monto_pagado = data.get('monto_pagado', 0)
        observaciones_pago = data.get('observaciones', '').strip()
        
        # Validaciones
        if not metodo_pago:
            return JsonResponse({'error': 'El método de pago es obligatorio'}, status=400)
        
        metodos_validos = ['EFECTIVO', 'TARJETA_CREDITO', 'TARJETA_DEBITO', 'TRANSFERENCIA', 'DIGITAL', 'MIXTO']
        if metodo_pago not in metodos_validos:
            return JsonResponse({'error': f'Método de pago inválido. Opciones: {", ".join(metodos_validos)}'}, status=400)
        
        try:
            monto_pagado = float(monto_pagado) if monto_pagado else float(factura.total)
        except (ValueError, TypeError):
            monto_pagado = float(factura.total)
        
        # Calcular cambio o faltante
        cambio = monto_pagado - float(factura.total)
        
        # Actualizar factura
        factura.estado_pago = 'PAGADA'
        factura.metodo_pago = metodo_pago
        factura.pagado_en = timezone.now()
        
        # Actualizar cliente si se proporcionó
        if cliente_nombre:
            factura.cliente_nombre = cliente_nombre
        
        # Agregar observaciones del pago
        obs_pago = f"Pago: {metodo_pago}"
        if monto_pagado != float(factura.total):
            obs_pago += f" - Monto: ${monto_pagado:,.2f}"
            if cambio > 0:
                obs_pago += f" - Cambio: ${cambio:,.2f}"
            elif cambio < 0:
                obs_pago += f" - Faltante: ${abs(cambio):,.2f}"
        
        if observaciones_pago:
            obs_pago += f" - {observaciones_pago}"
        
        if factura.observaciones:
            factura.observaciones += f"\n{obs_pago}"
        else:
            factura.observaciones = obs_pago
        
        factura.save()
        
        # Liberar la mesa si no está liberada
        orden = factura.orden
        if orden.mesa.numero not in [0, 50] and orden.mesa.estado != 'LIBRE':
            orden.mesa.estado = 'LIBRE'
            orden.mesa.save()
        
        # Preparar respuesta
        response_data = {
            'success': True,
            'mensaje': f'Factura #{factura.numero_factura or factura.id} marcada como pagada',
            'factura': {
                'id': factura.id,
                'numero': factura.numero_factura or f"FAC-{factura.id}",
                'total': float(factura.total),
                'monto_pagado': monto_pagado,
                'cambio': max(0, cambio),
                'faltante': max(0, abs(cambio)) if cambio < 0 else 0,
                'metodo_pago': metodo_pago,
                'estado_pago': factura.estado_pago,
                'cliente_nombre': factura.cliente_nombre,
                'pagado_en': factura.pagado_en.isoformat(),
                'observaciones': factura.observaciones
            },
            'orden': {
                'id': orden.id,
                'mesa_liberada': orden.mesa.numero not in [0, 50]
            }
        }
        
        if cambio > 0:
            response_data['mensaje'] += f' - Cambio: ${cambio:,.2f}'
        elif cambio < 0:
            response_data['mensaje'] += f' - Faltante registrado: ${abs(cambio):,.2f}'
        
        return JsonResponse(response_data)
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Formato JSON inválido'}, status=400)
    except Exception as e:
        print(f"❌ Error en api_marcar_factura_pagada: {str(e)}")
        return JsonResponse({'error': f'Error interno: {str(e)}'}, status=500)