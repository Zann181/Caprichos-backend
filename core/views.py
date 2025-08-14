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
from .models import Producto, CategoriaProducto, Mesa, Orden, OrdenProducto, Factura
from .utils import (
    long_polling_cocina, long_polling_meseros, obtener_todas_ordenes_cocina,
    obtener_stock_productos, notificar_cambio_cocina, notificar_cambio_stock,
    obtener_estadisticas_sistema, obtener_datos_completos_orden,
    calcular_total_orden,  # ✅ AGREGAR ESTA IMPORTACIÓN
)


from django.db.models import Q  # ✅ AGREGAR ESTA IMPORTACIÓN
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

# ...existing code...
@group_required(allowed_groups=['Meseros', 'Administradores'])
def mesero_nuevo_pedido(request):
    """Renderiza la pestaña de nuevo pedido para meseros."""
    categorias = CategoriaProducto.objects.filter(is_active=True).prefetch_related('productos')
    # Mesas libres + 0 y 50 siempre disponibles
    mesas_libres = Mesa.objects.filter(is_active=True, estado='LIBRE').exclude(numero__in=[0, 50])
    mesas_domicilio = Mesa.objects.filter(is_active=True, numero__in=[0, 50])
    mesas = list(mesas_libres) + list(mesas_domicilio)
    context = {
        'user': request.user,
        'categorias': categorias,
        'mesas': mesas
    }
    return render(request, 'mesero/nuevo_pedido.html', context)
# ...existing code...
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
# Reemplazar esta función en core/views.py

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
# REEMPLAZAR LA FUNCIÓN api_get_mesas_ocupadas EN core/views.py

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


# TAMBIÉN CORREGIR LA FUNCIÓN ALTERNATIVA api_get_mesas_ocupadas_detallado

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
                mesas_data.append({
                    'id': f"{mesa_domicilio.id}-{orden.id}",  # ID único combinado
                    'numero': f"{mesa_domicilio.numero}.{i+1}",  # Ej: "0.1", "0.2", "50.1"
                    'ubicacion': f'Domicilio #{i+1}',
                    'capacidad': 999,
                    'productos_count': orden.productos_ordenados.count(),
                    'tiene_orden': True,
                    'orden_id': orden.id,
                    'es_domicilio': True,
                    'ordenes_count': 1,
                    'mesa_real_id': mesa_domicilio.id  # ✅ ID real de la mesa para referencias
                })
            
            # Si no hay órdenes, mostrar mesa domicilio disponible
            if not todas_las_ordenes.exists():
                mesas_data.append({
                    'id': mesa_domicilio.id,
                    'numero': mesa_domicilio.numero,
                    'ubicacion': 'Domicilio (Disponible)',
                    'capacidad': 999,
                    'productos_count': 0,
                    'tiene_orden': False,
                    'orden_id': None,
                    'es_domicilio': True,
                    'ordenes_count': 0
                })
        
        return JsonResponse(mesas_data, safe=False)
        
    except Exception as e:
        print(f"❌ Error en api_get_mesas_ocupadas_detallado: {str(e)}")
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


# AGREGAR ESTAS FUNCIONES AL FINAL DEL ARCHIVO core/views.py

# === FUNCIÓN UTILITARIA PARA TIEMPO ===
def calcular_tiempo_transcurrido(fecha_creacion):
    """Calcula el tiempo transcurrido desde la creación"""
    from django.utils import timezone
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

# === API PARA MARCAR ORDEN COMO LISTA (MANUALMENTE) ===
@require_POST
@login_required
@transaction.atomic
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

# === API PARA OBTENER TODAS LAS ÓRDENES DEL MESERO (INCLUYENDO SERVIDAS) ===

# 2. AGREGAR FUNCIONES UTILITARIAS PARA EXTRAER INFORMACIÓN DE CLIENTE


def extraer_info_cliente_domicilio(observaciones):
    """Extrae información del cliente de domicilio de las observaciones"""
    if not observaciones:
        return {'nombre': 'Cliente Domicilio', 'direccion': '', 'telefono': ''}
    
    try:
        # Buscar patrones en las observaciones
        # Formato esperado: "Cliente: Juan Pérez, Tel: 123456789, Dir: Calle 123"
        import re
        
        nombre_match = re.search(r'Cliente:\s*([^,]+)', observaciones, re.IGNORECASE)
        telefono_match = re.search(r'Tel(?:éfono)?:\s*([^,]+)', observaciones, re.IGNORECASE)
        direccion_match = re.search(r'Dir(?:ección)?:\s*([^,\n]+)', observaciones, re.IGNORECASE)
        
        return {
            'nombre': nombre_match.group(1).strip() if nombre_match else 'Cliente Domicilio',
            'telefono': telefono_match.group(1).strip() if telefono_match else '',
            'direccion': direccion_match.group(1).strip() if direccion_match else observaciones[:50] + '...' if len(observaciones) > 50 else observaciones
        }
    except Exception:
        return {'nombre': 'Cliente Domicilio', 'direccion': observaciones[:50], 'telefono': ''}

def extraer_info_cliente_reserva(observaciones):
    """Extrae información del cliente de reserva de las observaciones"""
    if not observaciones:
        return {'nombre': 'Cliente Reserva', 'personas': 2, 'telefono': '', 'fecha_reserva': '', 'observaciones': ''}
    
    try:
        import re
        
        # Buscar patrones en las observaciones de reserva
        # Formato esperado: "Reserva: María García, Tel: 987654321, Personas: 4, Fecha: 2025-08-15 19:00"
        nombre_match = re.search(r'(?:Reserva|Cliente):\s*([^,]+)', observaciones, re.IGNORECASE)
        telefono_match = re.search(r'Tel(?:éfono)?:\s*([^,]+)', observaciones, re.IGNORECASE)
        personas_match = re.search(r'Personas?:\s*(\d+)', observaciones, re.IGNORECASE)
        fecha_match = re.search(r'Fecha:\s*([^,\n]+)', observaciones, re.IGNORECASE)
        
        return {
            'nombre': nombre_match.group(1).strip() if nombre_match else 'Cliente Reserva',
            'telefono': telefono_match.group(1).strip() if telefono_match else '',
            'personas': int(personas_match.group(1)) if personas_match else 2,
            'fecha_reserva': fecha_match.group(1).strip() if fecha_match else '',
            'observaciones': observaciones
        }
    except Exception:
        return {'nombre': 'Cliente Reserva', 'personas': 2, 'telefono': '', 'fecha_reserva': '', 'observaciones': observaciones}



def extraer_info_cliente_reserva(observaciones):
    """Extrae información del cliente de reserva de las observaciones"""
    if not observaciones:
        return {'nombre': 'Cliente Reserva', 'personas': 2, 'telefono': '', 'fecha_reserva': '', 'observaciones': ''}
    
    try:
        import re
        
        # Buscar patrones en las observaciones de reserva
        # Formato esperado: "Reserva: María García, Tel: 987654321, Personas: 4, Fecha: 2025-08-15 19:00"
        nombre_match = re.search(r'(?:Reserva|Cliente):\s*([^,]+)', observaciones, re.IGNORECASE)
        telefono_match = re.search(r'Tel(?:éfono)?:\s*([^,]+)', observaciones, re.IGNORECASE)
        personas_match = re.search(r'Personas?:\s*(\d+)', observaciones, re.IGNORECASE)
        fecha_match = re.search(r'Fecha:\s*([^,\n]+)', observaciones, re.IGNORECASE)
        
        return {
            'nombre': nombre_match.group(1).strip() if nombre_match else 'Cliente Reserva',
            'telefono': telefono_match.group(1).strip() if telefono_match else '',
            'personas': int(personas_match.group(1)) if personas_match else 2,
            'fecha_reserva': fecha_match.group(1).strip() if fecha_match else '',
            'observaciones': observaciones
        }
    except Exception:
        return {'nombre': 'Cliente Reserva', 'personas': 2, 'telefono': '', 'fecha_reserva': '', 'observaciones': observaciones}



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

# === API PARA OBTENER FACTURA POR ORDEN ===
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



# AGREGAR ESTAS FUNCIONES AL FINAL DEL ARCHIVO core/views.py

# === FUNCIÓN UTILITARIA PARA TIEMPO ===
def calcular_tiempo_transcurrido(fecha_creacion):
    """Calcula el tiempo transcurrido desde la creación"""
    from django.utils import timezone
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

# === API PARA MARCAR ORDEN COMO LISTA (MANUALMENTE) ===
@require_POST
@login_required
@transaction.atomic
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

# === API PARA OBTENER TODAS LAS ÓRDENES DEL MESERO (INCLUYENDO SERVIDAS) ===
# REEMPLAZAR/AGREGAR ESTAS FUNCIONES EN core/views.py

# === API MEJORADA PARA OBTENER TODAS LAS ÓRDENES DEL MESERO ===
@login_required
def api_get_todas_ordenes_mesero(request):
    """API mejorada para obtener todas las órdenes del mesero"""
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
            # NUEVO: Órdenes servidas pero con factura pendiente
            ordenes_query = ordenes_query.filter(
                estado='SERVIDA',
                factura__estado_pago__in=['NO_PAGADA', 'PARCIAL']
            )
        # Para 'todas' limitamos a recientes
        
        # Ordenar por fecha y limitar
        if filtro == 'todas':
            from datetime import timedelta
            fecha_limite = timezone.now() - timedelta(days=7)
            ordenes_query = ordenes_query.filter(creado_en__gte=fecha_limite)
            
        ordenes = ordenes_query.order_by('-creado_en')[:50]
        
        ordenes_data = []
        for orden in ordenes:
            orden_data = obtener_datos_completos_orden(orden)
            
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
            
            # Determinar si es domicilio
            es_domicilio = orden.mesa.numero == 0
            
            # Agregar información adicional para meseros
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
                'tiempo_transcurrido': calcular_tiempo_transcurrido(orden.creado_en),
            })
            
            ordenes_data.append(orden_data)
        
        return JsonResponse(ordenes_data, safe=False)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# === API PARA MARCAR ORDEN COMO LISTA DESDE MODIFICAR ===
@require_POST
@login_required
@transaction.atomic
def api_marcar_lista_desde_modificar(request, orden_id):
    """API para marcar orden como lista desde la pantalla de modificar"""
    try:
        orden = get_object_or_404(Orden, id=orden_id)
        
        if orden.mesero != request.user and not request.user.is_superuser:
            return JsonResponse({'error': 'Solo puedes confirmar tus propias órdenes'}, status=403)
        
        if orden.estado not in ['EN_PROCESO']:
            return JsonResponse({'error': f'La orden debe estar en proceso. Estado actual: {orden.estado}'}, status=400)
        
        # Marcar todos los productos pendientes como listos
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
        
        # Si ya tiene factura, crear nueva factura con productos agregados
        tiene_factura_existente = hasattr(orden, 'factura')
        nueva_factura_creada = False
        
        if not tiene_factura_existente:
            # Calcular total y crear factura
            total_orden = sum(item.cantidad * item.precio_unitario for item in orden.productos_ordenados.all())
            
            Factura.objects.create(
                orden=orden,
                subtotal=total_orden,
                total=total_orden,
                estado_pago='NO_PAGADA'
            )
            nueva_factura_creada = True
        
        # Notificar cambios
        notificar_cambio_cocina()
        
        respuesta = {
            'success': True,
            'mensaje': f'Orden #{orden_id} confirmada como lista',
            'productos_actualizados': productos_actualizados,
            'nueva_factura_creada': nueva_factura_creada,
            'orden_data': obtener_datos_completos_orden(orden)
        }
        
        if nueva_factura_creada:
            respuesta['mensaje'] += ' y factura generada'
            
        return JsonResponse(respuesta)
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

# === API MEJORADA PARA AGREGAR PRODUCTOS A ORDEN FACTURADA ===
@require_POST
@login_required
@transaction.atomic
def api_agregar_productos_orden_facturada(request, orden_id):
    """API mejorada para agregar productos a orden con factura"""
    try:
        orden = get_object_or_404(Orden, id=orden_id)
        
        if orden.mesero != request.user and not request.user.is_superuser:
            return JsonResponse({'error': 'Solo puedes modificar tus propias órdenes'}, status=403)
        
        # Verificar que tenga factura pendiente
        try:
            factura = orden.factura
            if factura.estado_pago not in ['NO_PAGADA', 'PARCIAL']:
                return JsonResponse({'error': 'La factura ya está pagada, no se puede modificar'}, status=400)
        except:
            return JsonResponse({'error': 'Esta orden no tiene factura'}, status=404)
        
        data = json.loads(request.body)
        productos_nuevos = data.get('productos', [])
        confirmar_automatico = data.get('confirmar_automatico', False)  # NUEVO
        
        if not productos_nuevos:
            return JsonResponse({'error': 'No hay productos para agregar'}, status=400)
        
        # Validar stock
        for item in productos_nuevos:
            producto = Producto.objects.get(id=item['id'])
            if producto.cantidad < item['cantidad']:
                return JsonResponse({'error': f'Stock insuficiente para {producto.nombre}.'}, status=400)
        
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
            
            # Estado inicial según confirmación automática
            estado_inicial = 'LISTO' if confirmar_automatico else 'PENDIENTE'
            listo_en = timezone.now() if confirmar_automatico else None
            
            nuevo_producto_orden = OrdenProducto.objects.create(
                orden=orden,
                producto=producto,
                cantidad=item['cantidad'],
                precio_unitario=producto.precio,
                observaciones=obs_final,
                estado=estado_inicial,
                listo_en=listo_en
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
        
        # Actualizar estado de la orden según confirmación
        if confirmar_automatico:
            # Si se confirma automático, mantener como LISTA si todos están listos
            productos_pendientes = orden.productos_ordenados.filter(estado='PENDIENTE').count()
            if productos_pendientes == 0:
                orden.estado = 'LISTA'
                orden.listo_en = timezone.now()
            else:
                orden.estado = 'EN_PROCESO'
                orden.listo_en = None
        else:
            # Si no se confirma automático, volver a EN_PROCESO
            orden.estado = 'EN_PROCESO'
            orden.listo_en = None
        
        orden.save()
        
        # Notificar cambios
        notificar_cambio_cocina()
        notificar_cambio_stock()
        
        mensaje = f'Se agregaron {len(productos_nuevos)} productos a la orden facturada'
        if confirmar_automatico:
            mensaje += ' y se confirmaron automáticamente'
        else:
            mensaje += '. La orden fue enviada a cocina para confirmación'
        
        return JsonResponse({
            'success': True,
            'mensaje': mensaje,
            'productos_agregados': len(productos_agregados),
            'total_agregado': float(total_agregado),
            'nueva_factura_total': float(factura.total),
            'confirmado_automatico': confirmar_automatico,
            'orden_data': obtener_datos_completos_orden(orden)
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# === API PARA OBTENER MESAS OCUPADAS (INCLUYENDO DOMICILIO) ===

@login_required
def api_get_mesas_ocupadas(request):
    """API mejorada para mesas ocupadas - cada orden de domicilio/reserva por separado"""
    try:
        mesas_data = []
        
        # === MESAS FÍSICAS NORMALES (1-49, excluyendo 0 y 50) ===
        mesas_fisicas_ocupadas = Mesa.objects.filter(
            is_active=True,
            estado='OCUPADA'
        ).exclude(
            numero__in=[0, 50]  # ✅ Excluir domicilios y reservas
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
                    'ordenes_count': 1,
                    'cliente_nombre': None
                })
        
        # === MESA 0: DOMICILIOS - CADA ORDEN POR SEPARADO ===
        mesa_domicilio = Mesa.objects.filter(is_active=True, numero=0).first()
        
        if mesa_domicilio:
            # Obtener todas las órdenes activas de domicilio
            try:
                ordenes_domicilio_activas = Orden.objects.filter(
                    mesa=mesa_domicilio,
                    estado__in=['EN_PROCESO', 'LISTA', 'NUEVA']
                )
                
                ordenes_domicilio_no_pagadas = Orden.objects.filter(
                    mesa=mesa_domicilio,
                    estado='SERVIDA',
                    factura__estado_pago__in=['NO_PAGADA', 'PARCIAL']
                )
                
                # Combinar usando union
                ordenes_domicilio = ordenes_domicilio_activas.union(
                    ordenes_domicilio_no_pagadas
                ).order_by('-creado_en')
                
            except Exception as e:
                print(f"⚠️ Error obteniendo órdenes de domicilio: {e}")
                ordenes_domicilio = ordenes_domicilio_activas.order_by('-creado_en')
            
            # Crear una entrada por cada orden de domicilio
            for i, orden in enumerate(ordenes_domicilio):
                # Extraer información del cliente de las observaciones
                cliente_info = extraer_info_cliente_domicilio(orden.observaciones)
                
                mesas_data.append({
                    'id': f"dom-{orden.id}",  # ID único para domicilio
                    'numero': f"🏠D{i+1}",  # Ej: "🏠D1", "🏠D2"
                    'ubicacion': f'Domicilio #{i+1}',
                    'capacidad': 999,
                    'productos_count': orden.productos_ordenados.count(),
                    'tiene_orden': True,
                    'orden_id': orden.id,
                    'es_domicilio': True,
                    'es_reserva': False,
                    'ordenes_count': 1,
                    'mesa_real_id': mesa_domicilio.id,
                    'cliente_nombre': cliente_info.get('nombre'),
                    'direccion': cliente_info.get('direccion'),
                    'telefono': cliente_info.get('telefono')
                })
        
        # === MESA 50: RESERVAS - CADA RESERVA POR SEPARADO ===
        mesa_reserva = Mesa.objects.filter(is_active=True, numero=50).first()
        
        if mesa_reserva:
            # Obtener todas las reservas activas
            try:
                ordenes_reserva_activas = Orden.objects.filter(
                    mesa=mesa_reserva,
                    estado__in=['EN_PROCESO', 'LISTA', 'NUEVA']
                )
                
                ordenes_reserva_no_pagadas = Orden.objects.filter(
                    mesa=mesa_reserva,
                    estado='SERVIDA',
                    factura__estado_pago__in=['NO_PAGADA', 'PARCIAL']
                )
                
                # Combinar usando union
                ordenes_reserva = ordenes_reserva_activas.union(
                    ordenes_reserva_no_pagadas
                ).order_by('-creado_en')
                
            except Exception as e:
                print(f"⚠️ Error obteniendo órdenes de reserva: {e}")
                ordenes_reserva = ordenes_reserva_activas.order_by('-creado_en')
            
            # Crear una entrada por cada reserva
            for i, orden in enumerate(ordenes_reserva):
                # Extraer información del cliente de las observaciones de reserva
                cliente_info = extraer_info_cliente_reserva(orden.observaciones)
                
                mesas_data.append({
                    'id': f"res-{orden.id}",  # ID único para reserva
                    'numero': f"📅R{i+1}",  # Ej: "📅R1", "📅R2"
                    'ubicacion': f'Reserva #{i+1}',
                    'capacidad': cliente_info.get('personas', 2),
                    'productos_count': orden.productos_ordenados.count(),
                    'tiene_orden': True,
                    'orden_id': orden.id,
                    'es_domicilio': False,
                    'es_reserva': True,
                    'ordenes_count': 1,
                    'mesa_real_id': mesa_reserva.id,
                    'cliente_nombre': cliente_info.get('nombre'),
                    'telefono': cliente_info.get('telefono'),
                    'fecha_reserva': cliente_info.get('fecha_reserva'),
                    'observaciones_cliente': cliente_info.get('observaciones')
                })
        
        return JsonResponse(mesas_data, safe=False)
        
    except Exception as e:
        print(f"❌ Error en api_get_mesas_ocupadas: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)




# === FUNCIÓN ALTERNATIVA SI QUIERES MOSTRAR CADA ORDEN DE DOMICILIO POR SEPARADO ===
@login_required
def api_get_mesas_ocupadas_detallado(request):
    """Versión alternativa que muestra cada orden de domicilio por separado"""
    try:
        from django.db import models
        
        mesas_data = []
        
        # === MESAS FÍSICAS OCUPADAS ===
        mesas_fisicas_ocupadas = Mesa.objects.filter(
            is_active=True,
            estado='OCUPADA',
            numero__gt=0,
            numero__ne=50
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
            
            ordenes_no_pagadas = Orden.objects.filter(
                mesa=mesa_domicilio,
                estado='SERVIDA',
                factura__estado_pago__in=['NO_PAGADA', 'PARCIAL']
            )
            
            todas_las_ordenes = ordenes_activas.union(ordenes_no_pagadas)
            
            # Crear una entrada por cada orden
            for i, orden in enumerate(todas_las_ordenes):
                mesas_data.append({
                    'id': f"{mesa_domicilio.id}-{orden.id}",  # ID único combinado
                    'numero': f"{mesa_domicilio.numero}.{i+1}",  # Ej: "0.1", "0.2", "50.1"
                    'ubicacion': f'Domicilio #{i+1}',
                    'capacidad': 999,
                    'productos_count': orden.productos_ordenados.count(),
                    'tiene_orden': True,
                    'orden_id': orden.id,
                    'es_domicilio': True,
                    'ordenes_count': 1,
                    'mesa_real_id': mesa_domicilio.id  # ✅ ID real de la mesa para referencias
                })
            
            # Si no hay órdenes, mostrar mesa domicilio disponible
            if not todas_las_ordenes.exists():
                mesas_data.append({
                    'id': mesa_domicilio.id,
                    'numero': mesa_domicilio.numero,
                    'ubicacion': 'Domicilio (Disponible)',
                    'capacidad': 999,
                    'productos_count': 0,
                    'tiene_orden': False,
                    'orden_id': None,
                    'es_domicilio': True,
                    'ordenes_count': 0
                })
        
        return JsonResponse(mesas_data, safe=False)
        
    except Exception as e:
        print(f"❌ Error en api_get_mesas_ocupadas_detallado: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# === API PARA OBTENER FACTURA POR ORDEN ===
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

# === API PARA AGREGAR PRODUCTOS A ORDEN CON FACTURA EXISTENTE ===
@require_POST
@login_required
@transaction.atomic
def api_agregar_productos_orden_facturada(request, orden_id):
    """API para agregar productos a una orden que ya tiene factura (cliente sigue en mesa)"""
    try:
        orden = get_object_or_404(Orden, id=orden_id)
        
        # Verificar que sea el mesero de la orden
        if orden.mesero != request.user and not request.user.is_superuser:
            return JsonResponse({'error': 'Solo puedes modificar tus propias órdenes'}, status=403)
        
        # Verificar que tenga factura pendiente
        try:
            factura = orden.factura
            if factura.estado_pago not in ['NO_PAGADA', 'PARCIAL']:
                return JsonResponse({'error': 'La factura ya está pagada, no se puede modificar'}, status=400)
        except:
            return JsonResponse({'error': 'Esta orden no tiene factura'}, status=404)
        
        data = json.loads(request.body)
        productos_nuevos = data.get('productos', [])
        
        if not productos_nuevos:
            return JsonResponse({'error': 'No hay productos para agregar'}, status=400)
        
        # Validar stock
        for item in productos_nuevos:
            producto = Producto.objects.get(id=item['id'])
            if producto.cantidad < item['cantidad']:
                return JsonResponse({'error': f'Stock insuficiente para {producto.nombre}.'}, status=400)
        
        # Agregar productos nuevos con marca especial
        productos_agregados = []
        total_agregado = 0
        
        for item in productos_nuevos:
            producto = Producto.objects.get(id=item['id'])
            
            # Marcar como agregado después de facturar
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
            'mensaje': f'Se agregaron {len(productos_nuevos)} productos a la orden facturada',
            'productos_agregados': len(productos_agregados),
            'total_agregado': float(total_agregado),
            'nueva_factura_total': float(factura.total),
            'orden_data': obtener_datos_completos_orden(orden)
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)