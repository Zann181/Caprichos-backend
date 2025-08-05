# core/views.py

import json
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.db import transaction

# Se importan los formularios, decoradores y modelos necesarios
from .forms import CustomAuthenticationForm
from .decorators import group_required 
from .models import Producto, CategoriaProducto, Mesa, Orden, OrdenProducto
from django.utils import timezone 
# --- Vistas de Autenticación ---
from .utils import (
    long_polling_cocina, long_polling_meseros, obtener_todas_ordenes_cocina,
    obtener_stock_productos, notificar_cambio_cocina, notificar_cambio_stock,
    obtener_estadisticas_sistema, obtener_datos_completos_orden
)


class UserLoginView(LoginView):
    """
    Gestiona el inicio de sesión del usuario.
    """
    template_name = 'login.html'
    form_class = CustomAuthenticationForm
    success_url = reverse_lazy('dashboard')

class UserLogoutView(LogoutView):
    """
    Gestiona el cierre de sesión del usuario.
    """
    next_page = reverse_lazy('login')

# --- Vista "Router" y Dashboards por Roles ---

@login_required
def dashboard_redirect(request):
    """
    Redirige al usuario a su panel de control correspondiente
    basado en el GRUPO al que pertenece.
    """
    user = request.user
    
    # El superusuario siempre va a su dashboard
    if user.is_superuser:
        return redirect('dashboard_admin')

    # Obtiene el primer grupo del usuario
    grupo = user.groups.first()
    
    if grupo:
        if grupo.name == 'Administradores':
            return redirect('dashboard_admin')
        elif grupo.name == 'Meseros':
            return redirect('dashboard_mesero')
        elif grupo.name == 'Cocineros':
            return redirect('dashboard_cocinero')
        elif grupo.name == 'Cajeros':
            return redirect('dashboard_cajero')
            
    # Si el usuario no tiene grupo, se le niega el acceso
    return redirect('acceso_denegado')

@group_required(allowed_groups=['Administradores'])
def dashboard_admin(request):
    """
    Renderiza el panel de control para Administradores.
    """
    return render(request, 'dashboards/admin_dashboard.html')

@group_required(allowed_groups=['Meseros', 'Administradores'])
def dashboard_mesero(request):
    """
    Renderiza el panel de control para Meseros, cargando
    las categorías, productos y mesas disponibles.
    """
    categorias = CategoriaProducto.objects.filter(is_active=True).prefetch_related('productos')
    mesas = Mesa.objects.filter(is_active=True, estado='LIBRE')
    context = {
        'user': request.user, 
        'categorias': categorias, 
        'mesas': mesas
    }
    return render(request, 'dashboards/mesero_dashboard.html', context)

@group_required(allowed_groups=['Cocineros', 'Administradores'])
def dashboard_cocinero(request):
    """
    Renderiza el panel de control para Cocineros.
    """
    return render(request, 'dashboards/cocinero_dashboard.html')

@group_required(allowed_groups=['Cajeros', 'Administradores'])
def dashboard_cajero(request):
    """
    Renderiza el panel de control para Cajeros.
    """
    return render(request, 'dashboards/cajero_dashboard.html')

def acceso_denegado_view(request):
    """
    Muestra la página de "Acceso Denegado".
    """
    return render(request, 'acceso_denegado.html')

# --- API Endpoints (Puntos de acceso para CRUD y lógica) ---

@require_http_methods(["GET", "POST"])
def api_productos_list_create(request):
    """
    API para listar (GET) o crear (POST) productos.
    """
    if request.method == 'GET':
        productos = Producto.objects.filter(is_active=True).values('id', 'nombre', 'precio', 'cantidad', 'id_categoria__nombre')
        return JsonResponse(list(productos), safe=False)
    
    elif request.method == 'POST':
        try:
            data = json.loads(request.body)
            categoria = get_object_or_404(CategoriaProducto, id=data['id_categoria'])
            producto = Producto.objects.create(
                nombre=data['nombre'],
                descripcion=data.get('descripcion', ''),
                cantidad=data.get('cantidad', 0),
                precio=data['precio'],
                id_categoria=categoria
            )
            return JsonResponse({'id': producto.id, 'nombre': producto.nombre}, status=201)
        except (KeyError, CategoriaProducto.DoesNotExist):
            return JsonResponse({'error': 'Datos inválidos o categoría no encontrada.'}, status=400)

@require_http_methods(["GET", "PUT", "DELETE"])
def api_producto_detail(request, pk):
    """
    API para ver (GET), actualizar (PUT) o borrar (DELETE) un producto específico.
    """
    producto = get_object_or_404(Producto, pk=pk)
    
    if request.method == 'GET':
        data = {'id': producto.id, 'nombre': producto.nombre, 'precio': str(producto.precio), 'cantidad': producto.cantidad}
        return JsonResponse(data)
        
    elif request.method == 'PUT':
        data = json.loads(request.body)
        producto.nombre = data.get('nombre', producto.nombre)
        producto.precio = data.get('precio', producto.precio)
        producto.cantidad = data.get('cantidad', producto.cantidad)
        producto.save()
        return JsonResponse({'id': producto.id, 'nombre': producto.nombre})
        
    elif request.method == 'DELETE':
        producto.delete()
        return HttpResponse(status=204) # 204 No Content, significa éxito sin contenido que devolver

@require_POST
@transaction.atomic
def api_crear_orden(request):
    """
    API para recibir y procesar un nuevo pedido.
    Valida el stock y lo descuenta de forma segura.
    """
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
        nueva_orden = Orden.objects.create(mesero=mesero, mesa=mesa, estado='EN_PROCESO')
        
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
        return JsonResponse({'success': True, 'orden_id': nueva_orden.id}, status=201)

    except (KeyError, Mesa.DoesNotExist, Producto.DoesNotExist):
        return JsonResponse({'error': 'Datos inválidos en el pedido.'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# Agregar estas funciones a core/views.py

@login_required
def api_get_ordenes_cocina(request):
    """
    API que devuelve las órdenes activas para la cocina en formato JSON.
    Incluye observaciones de la orden y información completa.
    """
    # Buscamos órdenes que estén en proceso o recién enviadas
    ordenes = Orden.objects.filter(estado__in=['EN_PROCESO', 'NUEVA']).order_by('creado_en')
    
    lista_ordenes = []
    for orden in ordenes:
        productos_ordenados = orden.productos_ordenados.all()
        lista_productos = []
        
        todos_listos = True
        for po in productos_ordenados:
            if po.estado != 'LISTO':
                todos_listos = False
            lista_productos.append({
                'id': po.id,
                'nombre': po.producto.nombre,
                'cantidad': po.cantidad,
                'observaciones': po.observaciones or '',  # Observaciones del producto
                'estado': po.estado
            })
        
        lista_ordenes.append({
            'id': orden.id,
            'mesa': orden.mesa.numero,
            'mesero': orden.mesero.nombre,
            'creado_en': orden.creado_en.strftime('%I:%M %p'),
            'observaciones': orden.observaciones or '',  # Observaciones de la orden completa
            'productos': lista_productos,
            'completada': todos_listos
        })
        
    return JsonResponse(lista_ordenes, safe=False)


@require_POST
@login_required
@transaction.atomic
def api_decrementar_producto(request, producto_orden_id):
    """
    API para decrementar la cantidad de un producto específico en una orden.
    Si la cantidad llega a 0, elimina el producto de la orden.
    """
    try:
        # Verificar que el producto_orden existe
        try:
            producto_orden = OrdenProducto.objects.get(id=producto_orden_id)
        except OrdenProducto.DoesNotExist:
            return JsonResponse({'error': f'No se encontró el producto con ID {producto_orden_id}'}, status=404)
        
        orden = producto_orden.orden
        
        # Debug info - eliminar en producción
        print(f"DEBUG: Intentando decrementar producto {producto_orden_id}")
        print(f"DEBUG: Orden estado: {orden.estado}")
        print(f"DEBUG: Producto estado: {producto_orden.estado}")
        print(f"DEBUG: Cantidad actual: {producto_orden.cantidad}")
        
        # Verificar que la orden esté activa
        if orden.estado not in ['EN_PROCESO', 'NUEVA']:
            return JsonResponse({
                'error': f'No se puede modificar una orden con estado: {orden.estado}. Solo se permiten órdenes NUEVA o EN_PROCESO'
            }, status=400)
        
        # Verificar que el producto no esté ya completado
        if producto_orden.estado == 'LISTO':
            return JsonResponse({
                'error': 'No se puede decrementar un producto ya completado'
            }, status=400)
        
        # Verificar que la cantidad sea válida
        if producto_orden.cantidad <= 0:
            return JsonResponse({
                'error': f'La cantidad actual es {producto_orden.cantidad}, no se puede decrementar'
            }, status=400)
        
        if producto_orden.cantidad > 1:
            # Decrementar cantidad
            producto_orden.cantidad -= 1
            producto_orden.save()
            
            # Devolver stock al inventario
            producto = producto_orden.producto
            producto.cantidad += 1
            producto.save()
            
            print(f"DEBUG: Cantidad decrementada exitosamente a {producto_orden.cantidad}")
            
            return JsonResponse({
                'success': True, 
                'nueva_cantidad': producto_orden.cantidad,
                'mensaje': f'Cantidad reducida a {producto_orden.cantidad}'
            })
        else:
            # Si la cantidad es 1, eliminar el producto de la orden
            producto = producto_orden.producto
            producto.cantidad += 1  # Devolver stock
            producto.save()
            
            # Guardar información antes de eliminar
            orden_id = orden.id
            producto_nombre = producto_orden.producto.nombre
            
            producto_orden.delete()
            
            print(f"DEBUG: Producto {producto_nombre} eliminado de la orden {orden_id}")
            
            # Verificar si la orden se quedó sin productos
            if not orden.productos_ordenados.exists():
                # Si no quedan productos, cambiar estado de la mesa
                orden.mesa.estado = 'LIBRE'
                orden.mesa.save()
                orden.delete()
                
                print(f"DEBUG: Orden {orden_id} eliminada por falta de productos")
                
                return JsonResponse({
                    'success': True, 
                    'orden_eliminada': True,
                    'mensaje': f'Producto {producto_nombre} eliminado. Orden completa cancelada por falta de productos.'
                })
            
            return JsonResponse({
                'success': True, 
                'producto_eliminado': True,
                'mensaje': f'Producto {producto_nombre} eliminado de la orden'
            })
            
    except Exception as e:
        # Log del error completo
        import traceback
        error_traceback = traceback.format_exc()
        print(f"ERROR en api_decrementar_producto: {str(e)}")
        print(f"TRACEBACK: {error_traceback}")
        
        return JsonResponse({
            'error': f'Error interno del servidor: {str(e)}'
        }, status=500)


@require_POST
@login_required  
def api_marcar_producto_listo(request, producto_orden_id):
    """
    API para marcar un producto específico de una orden como 'LISTO'.
    Versión con mejor manejo de errores.
    """
    try:
        # Verificar que el producto_orden existe
        try:
            producto_orden = OrdenProducto.objects.get(id=producto_orden_id)
        except OrdenProducto.DoesNotExist:
            return JsonResponse({'error': f'No se encontró el producto con ID {producto_orden_id}'}, status=404)
        
        # Debug info
        print(f"DEBUG: Marcando producto {producto_orden_id} como listo")
        print(f"DEBUG: Estado actual: {producto_orden.estado}")
        
        # Verificar que no esté ya listo
        if producto_orden.estado == 'LISTO':
            return JsonResponse({'error': 'El producto ya está marcado como listo'}, status=400)
        
        producto_orden.estado = 'LISTO'
        producto_orden.listo_en = timezone.now()
        producto_orden.save()

        # Comprobar si todos los productos de la orden están listos
        orden = producto_orden.orden
        productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
        
        print(f"DEBUG: Productos pendientes restantes: {productos_pendientes}")
        
        if productos_pendientes == 0:
            orden.estado = 'LISTA'
            orden.listo_en = timezone.now()
            orden.save()
            
            print(f"DEBUG: Orden {orden.id} marcada como LISTA")
            
            return JsonResponse({
                'success': True,
                'producto_listo': True,
                'orden_completa': True,
                'mensaje': f'¡Orden #{orden.id} completa y lista para servir!'
            })
        else:
            return JsonResponse({
                'success': True,
                'producto_listo': True,
                'orden_completa': False,
                'productos_restantes': productos_pendientes,
                'mensaje': f'Producto completado. Faltan {productos_pendientes} productos.'
            })
            
    except Exception as e:
        # Log del error completo
        import traceback
        error_traceback = traceback.format_exc()
        print(f"ERROR en api_marcar_producto_listo: {str(e)}")
        print(f"TRACEBACK: {error_traceback}")
        
        return JsonResponse({
            'error': f'Error interno del servidor: {str(e)}'
        }, status=500)


@login_required
def api_get_ordenes_cocina(request):
    """
    API que devuelve las órdenes activas para la cocina en formato JSON.
    Versión con mejor manejo de errores.
    """
    try:
        # Buscamos órdenes que estén en proceso o recién enviadas
        ordenes = Orden.objects.filter(estado__in=['EN_PROCESO', 'NUEVA']).order_by('creado_en')
        
        print(f"DEBUG: Encontradas {ordenes.count()} órdenes activas")
        
        lista_ordenes = []
        for orden in ordenes:
            try:
                productos_ordenados = orden.productos_ordenados.all()
                lista_productos = []
                
                todos_listos = True
                for po in productos_ordenados:
                    if po.estado != 'LISTO':
                        todos_listos = False
                    lista_productos.append({
                        'id': po.id,
                        'nombre': po.producto.nombre,
                        'cantidad': po.cantidad,
                        'observaciones': po.observaciones or '',
                        'estado': po.estado
                    })
                
                lista_ordenes.append({
                    'id': orden.id,
                    'mesa': orden.mesa.numero,
                    'mesero': orden.mesero.nombre,
                    'creado_en': orden.creado_en.strftime('%I:%M %p'),
                    'observaciones': orden.observaciones or '',
                    'productos': lista_productos,
                    'completada': todos_listos
                })
                
            except Exception as e:
                print(f"ERROR procesando orden {orden.id}: {str(e)}")
                continue
        
        print(f"DEBUG: Devolviendo {len(lista_ordenes)} órdenes procesadas")
        return JsonResponse(lista_ordenes, safe=False)
        
    except Exception as e:
        import traceback
        error_traceback = traceback.format_exc()
        print(f"ERROR en api_get_ordenes_cocina: {str(e)}")
        print(f"TRACEBACK: {error_traceback}")
        
        return JsonResponse({
            'error': f'Error interno del servidor: {str(e)}'
        }, status=500)




# Agregar estas views a core/views.py - SIN MODIFICAR MODELOS

from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from .utils import (
    long_polling_cocina, long_polling_meseros, obtener_todas_ordenes_cocina,
    obtener_stock_productos, notificar_cambio_cocina, notificar_cambio_stock,
    obtener_estadisticas_sistema, obtener_datos_completos_orden
)

# === LONG POLLING ENDPOINTS ===

@never_cache
@login_required
def api_longpolling_cocina(request):
    """
    Long polling para el dashboard de cocina
    Detecta cambios en órdenes usando hash del estado
    """
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
    """
    Long polling para meseros
    Detecta cambios en stock usando hash
    """
    hash_stock_anterior = request.GET.get('hash_stock', None)
    
    try:
        resultado = long_polling_meseros(hash_stock_anterior, timeout=25)
        return JsonResponse(resultado)
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'cambios': False,
            'timestamp': timezone.now().isoformat()
        }, status=500)

@login_required
def api_estadisticas_sistema(request):
    """
    Endpoint para debugging del sistema de long polling
    """
    stats = obtener_estadisticas_sistema()
    return JsonResponse(stats)

# === LONG POLLING ENDPOINTS ===

@never_cache
@login_required
def api_longpolling_cocina(request):
    """
    Long polling para el dashboard de cocina
    Detecta cambios en órdenes usando hash del estado
    """
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
    """
    Long polling para meseros
    Detecta cambios en stock usando hash
    """
    hash_stock_anterior = request.GET.get('hash_stock', None)
    
    try:
        resultado = long_polling_meseros(hash_stock_anterior, timeout=25)
        return JsonResponse(resultado)
    except Exception as e:
        return JsonResponse({
            'error': str(e),
            'cambios': False,
            'timestamp': timezone.now().isoformat()
        }, status=500)

@login_required
def api_estadisticas_sistema(request):
    """
    Endpoint para debugging del sistema de long polling
    """
    stats = obtener_estadisticas_sistema()
    return JsonResponse(stats)

# === VIEWS ACTUALIZADAS CON NOTIFICACIONES ===

@require_POST
@transaction.atomic
def api_crear_orden_tiempo_real(request):
    """
    API para crear orden CON notificación en tiempo real
    """
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
        
        # 🚀 NOTIFICAR CAMBIOS EN TIEMPO REAL
        notificar_cambio_cocina()  # Notifica a cocina
        notificar_cambio_stock()   # Notifica cambio de stock a meseros
        
        # Obtener datos completos de la orden creada
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
def api_marcar_producto_listo_tiempo_real(request, producto_orden_id):
    """
    Marcar producto como listo CON notificación en tiempo real
    """
    try:
        producto_orden = get_object_or_404(OrdenProducto, id=producto_orden_id)
        
        if producto_orden.estado == 'LISTO':
            return JsonResponse({'error': 'El producto ya está marcado como listo'}, status=400)
        
        # Datos antes del cambio
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
        
        # 🚀 NOTIFICAR CAMBIOS
        notificar_cambio_cocina()
        
        # Obtener datos actualizados
        orden_data = obtener_datos_completos_orden(orden)
        
        response_data = {
            'success': True,
            'producto_listo': True,
            'producto_nombre': producto_nombre,
            'orden_completa': orden_completa,
            'productos_restantes': productos_pendientes,
            'orden_data': orden_data
        }
        
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
def api_decrementar_producto_tiempo_real(request, producto_orden_id):
    """
    Decrementar producto CON notificación en tiempo real
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
        
        if producto_orden.cantidad > 1:
            # Decrementar cantidad
            producto_orden.cantidad -= 1
            producto_orden.save()
            
            # Devolver stock
            producto = producto_orden.producto
            producto.cantidad += 1
            producto.save()
            
            # 🚀 NOTIFICAR CAMBIOS
            notificar_cambio_cocina()
            notificar_cambio_stock()  # Por el cambio de stock
            
            return JsonResponse({
                'success': True,
                'nueva_cantidad': producto_orden.cantidad,
                'mensaje': f'Cantidad reducida a {producto_orden.cantidad}',
                'orden_data': obtener_datos_completos_orden(orden)
            })
        else:
            # Eliminar producto si cantidad es 1
            producto = producto_orden.producto
            producto_nombre = producto_orden.producto.nombre
            producto.cantidad += 1
            producto.save()
            
            producto_orden.delete()
            
            # Verificar si quedan productos en la orden
            if not orden.productos_ordenados.exists():
                # Liberar mesa y eliminar orden
                orden.mesa.estado = 'LIBRE'
                orden.mesa.save()
                orden.delete()
                
                # 🚀 NOTIFICAR CAMBIOS
                notificar_cambio_cocina()
                notificar_cambio_stock()
                
                return JsonResponse({
                    'success': True,
                    'orden_eliminada': True,
                    'mensaje': f'Producto {producto_nombre} eliminado. Orden cancelada por falta de productos.'
                })
            
            # 🚀 NOTIFICAR CAMBIOS
            notificar_cambio_cocina()
            notificar_cambio_stock()
            
            return JsonResponse({
                'success': True,
                'producto_eliminado': True,
                'mensaje': f'Producto {producto_nombre} eliminado de la orden',
                'orden_data': obtener_datos_completos_orden(orden)
            })
            
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_POST
@login_required
@transaction.atomic
def api_marcar_orden_servida(request, orden_id):
    """
    API para marcar una orden completa como servida
    Libera la mesa y actualiza el estado
    """
    try:
        orden = get_object_or_404(Orden, id=orden_id)
        
        # Verificar que la orden esté lista
        if orden.estado != 'LISTA':
            return JsonResponse({
                'error': f'La orden debe estar en estado LISTA. Estado actual: {orden.estado}'
            }, status=400)
        
        # Verificar que todos los productos estén listos
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
        
        print(f"DEBUG: Orden {orden_id} marcada como servida. Mesa {mesa.numero} liberada.")
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Orden #{orden_id} servida exitosamente',
            'mesa': mesa.numero,
            'orden_id': orden_id
        })
        
    except Exception as e:
        print(f"ERROR en api_marcar_orden_servida: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)



@login_required
def api_get_ordenes_cocina(request):
    """
    API que devuelve las órdenes activas para la cocina en formato JSON.
    ACTUALIZADA: Incluye órdenes LISTA para mostrar en "Listas para Servir"
    """
    # ✅ CORREGIDO: Incluir también órdenes LISTA
    ordenes = Orden.objects.filter(estado__in=['EN_PROCESO', 'NUEVA', 'LISTA']).order_by('creado_en')
    
    print(f"DEBUG: Encontradas {ordenes.count()} órdenes activas (incluyendo listas)")
    
    lista_ordenes = []
    for orden in ordenes:
        try:
            productos_ordenados = orden.productos_ordenados.all()
            lista_productos = []
            
            # DEBUG: Imprimir observaciones de la orden
            print(f"DEBUG: Orden {orden.id} - Observaciones orden: '{orden.observaciones}'")
            
            todos_listos = True
            for po in productos_ordenados:
                if po.estado != 'LISTO':
                    todos_listos = False
                
                # DEBUG: Imprimir observaciones del producto
                print(f"DEBUG: Producto {po.id} ({po.producto.nombre}) - Observaciones: '{po.observaciones}'")
                
                lista_productos.append({
                    'id': po.id,
                    'nombre': po.producto.nombre,
                    'cantidad': po.cantidad,
                    'observaciones': po.observaciones if po.observaciones else '',
                    'estado': po.estado
                })
            
            orden_data = {
                'id': orden.id,
                'mesa': orden.mesa.numero,
                'mesero': orden.mesero.nombre,
                'creado_en': orden.creado_en.strftime('%I:%M %p'),
                'observaciones': orden.observaciones if orden.observaciones else '',
                'productos': lista_productos,
                'completada': todos_listos or orden.estado == 'LISTA'  # ✅ CORREGIDO: También considerar estado LISTA
            }
            
            # DEBUG: Imprimir datos finales de la orden
            print(f"DEBUG: Orden {orden.id} - Estado: {orden.estado}, Completada: {orden_data['completada']}")
            
            lista_ordenes.append(orden_data)
            
        except Exception as e:
            print(f"ERROR procesando orden {orden.id}: {str(e)}")
            continue
    
    print(f"DEBUG: Devolviendo {len(lista_ordenes)} órdenes procesadas")
    return JsonResponse(lista_ordenes, safe=False)