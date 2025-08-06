# core/views.py - ARCHIVO COMPLETO CON TODAS LAS VISTAS

import json
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods, require_POST
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.db import transaction
from django.utils import timezone

# Se importan los formularios, decoradores y modelos necesarios
from .forms import CustomAuthenticationForm
from .decorators import group_required 
from .models import Producto, CategoriaProducto, Mesa, Orden, OrdenProducto
from .utils import (
    long_polling_cocina, long_polling_meseros, obtener_todas_ordenes_cocina,
    obtener_stock_productos, notificar_cambio_cocina, notificar_cambio_stock,
    obtener_estadisticas_sistema, obtener_datos_completos_orden,
    calcular_total_orden  # ✅ AGREGAR ESTA IMPORTACIÓN
)



# === VISTAS DE AUTENTICACIÓN ===

class UserLoginView(LoginView):
    """Gestiona el inicio de sesión del usuario."""
    template_name = 'login.html'
    form_class = CustomAuthenticationForm
    success_url = reverse_lazy('dashboard')

class UserLogoutView(LogoutView):
    """Gestiona el cierre de sesión del usuario."""
    next_page = reverse_lazy('login')

# === DASHBOARDS PRINCIPALES ===

@login_required
def dashboard_redirect(request):
    """Redirige al usuario a su panel de control correspondiente basado en el GRUPO al que pertenece."""
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
    """Renderiza el panel de control para Administradores."""
    return render(request, 'dashboards/admin_dashboard.html')

@group_required(allowed_groups=['Meseros', 'Administradores'])
def dashboard_mesero(request):
    """Renderiza el panel de control principal para Meseros."""
    context = {'user': request.user}
    return render(request, 'dashboards/mesero_dashboard.html', context)

@group_required(allowed_groups=['Cocineros', 'Administradores'])
def dashboard_cocinero(request):
    """Renderiza el panel de control para Cocineros."""
    return render(request, 'dashboards/cocinero_dashboard.html')

@group_required(allowed_groups=['Cajeros', 'Administradores'])
def dashboard_cajero(request):
    """Renderiza el panel de control para Cajeros."""
    return render(request, 'dashboards/cajero_dashboard.html')

def acceso_denegado_view(request):
    """Muestra la página de "Acceso Denegado"."""
    return render(request, 'acceso_denegado.html')

# === VISTAS DE PESTAÑAS DE MESERO ===

@group_required(allowed_groups=['Meseros', 'Administradores'])
def mesero_nuevo_pedido(request):
    """Renderiza la pestaña de nuevo pedido para meseros."""
    categorias = CategoriaProducto.objects.filter(is_active=True).prefetch_related('productos')
    mesas = Mesa.objects.filter(is_active=True, estado='LIBRE')
    context = {
        'user': request.user,
        'categorias': categorias,
        'mesas': mesas
    }
    return render(request, 'mesero/nuevo_pedido.html', context)

@group_required(allowed_groups=['Meseros', 'Administradores'])
def mesero_modificar_orden(request):
    """Renderiza la pestaña de modificar orden para meseros."""
    categorias = CategoriaProducto.objects.filter(is_active=True).prefetch_related('productos')
    context = {
        'user': request.user,
        'categorias': categorias
    }
    return render(request, 'mesero/modificar_orden.html', context)

@group_required(allowed_groups=['Meseros', 'Administradores'])
def mesero_vista_cocina(request):
    """Renderiza la pestaña de vista de cocina para meseros."""
    context = {'user': request.user}
    return render(request, 'mesero/vista_cocina.html', context)

@group_required(allowed_groups=['Meseros', 'Administradores'])
def mesero_mis_ordenes(request):
    """Renderiza la pestaña de mis órdenes para meseros."""
    context = {'user': request.user}
    return render(request, 'mesero/mis_ordenes.html', context)

# === API PRODUCTOS (CRUD BÁSICO) ===

@require_http_methods(["GET", "POST"])
def api_productos_list_create(request):
    """API para listar (GET) o crear (POST) productos."""
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
    """API para ver (GET), actualizar (PUT) o borrar (DELETE) un producto específico."""
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
        return HttpResponse(status=204)

# === API ÓRDENES (CREAR Y GESTIONAR) ===

@require_POST
@transaction.atomic
def api_crear_orden_tiempo_real(request):
    """API para crear orden CON notificación en tiempo real"""
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
def api_agregar_productos_orden(request, orden_id):
    """API para agregar productos a una orden existente (usa observaciones para marcar como agregado después)"""
    try:
        orden = get_object_or_404(Orden, id=orden_id)
        data = json.loads(request.body)
        productos_nuevos = data.get('productos', [])
        
        if not productos_nuevos:
            return JsonResponse({'error': 'No hay productos para agregar'}, status=400)
        
        # Validar que la orden pueda ser modificada
        if orden.estado in ['SERVIDA']:
            return JsonResponse({'error': 'No se puede modificar una orden ya servida'}, status=400)
        
        # Validar stock
        for item in productos_nuevos:
            producto = Producto.objects.get(id=item['id'])
            if producto.cantidad < item['cantidad']:
                return JsonResponse({'error': f'Stock insuficiente para {producto.nombre}.'}, status=400)
        
        # Agregar productos nuevos con marca especial en observaciones
        productos_agregados = []
        for item in productos_nuevos:
            producto = Producto.objects.get(id=item['id'])
            
            # Usar observaciones para marcar como agregado después
            obs_producto = item.get('observaciones', '')
            if obs_producto:
                obs_final = f"AGREGADO_DESPUES|{obs_producto}"
            else:
                obs_final = "AGREGADO_DESPUES"
            
            nuevo_producto_orden = OrdenProducto.objects.create(
                orden=orden,
                producto=producto,
                cantidad=item['cantidad'],
                precio_unitario=producto.precio,
                observaciones=obs_final,
                estado='PENDIENTE'
            )
            
            productos_agregados.append(nuevo_producto_orden)
            
            # Descontar stock
            producto.cantidad -= item['cantidad']
            producto.save()
        
        # Si la orden estaba LISTA, volver a EN_PROCESO porque hay productos nuevos
        if orden.estado == 'LISTA':
            orden.estado = 'EN_PROCESO'
            orden.listo_en = None
            orden.save()
        
        # Notificar cambios
        notificar_cambio_cocina()
        notificar_cambio_stock()
        
        orden_completa = obtener_datos_completos_orden(orden)
        
        return JsonResponse({
            'success': True,
            'mensaje': f'Se agregaron {len(productos_nuevos)} productos a la orden',
            'productos_agregados': len(productos_agregados),
            'orden_data': orden_completa
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def api_get_orden_por_mesa(request, mesa_id):
    """API para obtener la orden activa de una mesa específica"""
    try:
        mesa = get_object_or_404(Mesa, id=mesa_id)
        
        # Buscar orden activa en esa mesa
        orden = Orden.objects.filter(
            mesa=mesa,
            estado__in=['EN_PROCESO', 'LISTA', 'NUEVA']
        ).first()
        
        if not orden:
            return JsonResponse({'error': 'No hay orden activa en esta mesa'}, status=404)
        
        orden_data = obtener_datos_completos_orden(orden)
        
        # Separar productos originales de los agregados después
        productos_originales = []
        productos_agregados = []
        
        for producto in orden_data['productos']:
            # Buscar el OrdenProducto para ver sus observaciones
            op = OrdenProducto.objects.get(id=producto['id'])
            if op.observaciones and 'AGREGADO_DESPUES' in op.observaciones:
                producto['agregado_despues'] = True
                productos_agregados.append(producto)
            else:
                producto['agregado_despues'] = False
                productos_originales.append(producto)
        
        orden_data['productos_originales'] = productos_originales
        orden_data['productos_agregados'] = productos_agregados
        orden_data['tiene_agregados'] = len(productos_agregados) > 0
        
        return JsonResponse(orden_data)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_POST
@login_required
@transaction.atomic
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
def api_get_mesas_ocupadas(request):
    """API para obtener mesas ocupadas con información básica"""
    try:
        mesas_ocupadas = Mesa.objects.filter(is_active=True, estado='OCUPADA')
        
        mesas_data = []
        for mesa in mesas_ocupadas:
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
                'orden_id': orden.id if orden else None
            })
        
        return JsonResponse(mesas_data, safe=False)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# === API COCINA ===

@login_required
def api_get_ordenes_cocina(request):
    """API que devuelve las órdenes activas para cocina (maneja productos agregados después)"""
    try:
        ordenes = Orden.objects.filter(
            estado__in=['EN_PROCESO', 'NUEVA', 'LISTA']
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
                
                orden_data = {
                    'id': orden.id,
                    'mesa': orden.mesa.numero,
                    'mesero': orden.mesero.nombre,
                    'creado_en': orden.creado_en.strftime('%I:%M %p'),
                    'observaciones': orden.observaciones if orden.observaciones else '',
                    'productos': lista_productos,
                    'completada': todos_listos or orden.estado == 'LISTA',
                    'tiene_agregados': any(p['agregado_despues'] for p in lista_productos)
                }
                
                lista_ordenes.append(orden_data)
                
            except Exception as e:
                print(f"ERROR procesando orden {orden.id}: {str(e)}")
                continue
        
        return JsonResponse(lista_ordenes, safe=False)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@require_POST
@login_required
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
# Agregar esta nueva vista al final de las APIs de mesero
@require_POST
@login_required
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
        from .models import Factura
        
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