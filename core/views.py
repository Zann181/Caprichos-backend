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

# --- Vistas de Autenticación ---

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



@login_required
def api_get_ordenes_cocina(request):
    """
    API que devuelve las órdenes activas para la cocina en formato JSON.
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
                'observaciones': po.observaciones,
                'estado': po.estado
            })
        
        lista_ordenes.append({
            'id': orden.id,
            'mesa': orden.mesa.numero,
            'mesero': orden.mesero.nombre,
            'creado_en': orden.creado_en.strftime('%I:%M %p'),
            'productos': lista_productos,
            'completada': todos_listos
        })
        
    return JsonResponse(lista_ordenes, safe=False)


@require_POST
@login_required
def api_marcar_producto_listo(request, producto_orden_id):
    """
    API para marcar un producto específico de una orden como 'LISTO'.
    """
    try:
        producto_orden = get_object_or_404(OrdenProducto, id=producto_orden_id)
        producto_orden.estado = 'LISTO'
        producto_orden.save()

        # Comprobar si todos los productos de la orden están listos
        orden = producto_orden.orden
        if not orden.productos_ordenados.filter(estado='PENDIENTE').exists():
            orden.estado = 'LISTA'
            orden.save()

        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
        