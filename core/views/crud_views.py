# core/views/crud_views.py
"""
Vistas CRUD básicas para entidades del sistema.
Operaciones simples de crear, leer, actualizar y eliminar sin lógica de negocio compleja.
"""

import json
from django.shortcuts import get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods

from ..decorators import debounce_request
from ..models import Producto, CategoriaProducto


# === API PRODUCTOS (CRUD BÁSICO) ===

@require_http_methods(["GET", "POST"])
@debounce_request(delay=0.5, include_data=True, error_message="⚠️ Operación muy rápida en productos.")
def api_productos_list_create(request):
    """API para listar (GET) o crear (POST) productos."""
    if request.method == 'GET':
        productos = Producto.objects.filter(is_active=True).values(
            'id', 'nombre', 'precio', 'cantidad', 'id_categoria__nombre'
        )
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
            
            return JsonResponse({
                'id': producto.id, 
                'nombre': producto.nombre
            }, status=201)
            
        except (KeyError, CategoriaProducto.DoesNotExist):
            return JsonResponse({
                'error': 'Datos inválidos o categoría no encontrada.'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'error': f'Error interno: {str(e)}'
            }, status=500)


@require_http_methods(["GET", "PUT", "DELETE"])
def api_producto_detail(request, pk):
    """API para ver (GET), actualizar (PUT) o borrar (DELETE) un producto específico."""
    producto = get_object_or_404(Producto, pk=pk)
    
    if request.method == 'GET':
        data = {
            'id': producto.id, 
            'nombre': producto.nombre, 
            'precio': str(producto.precio), 
            'cantidad': producto.cantidad,
            'descripcion': producto.descripcion,
            'categoria': producto.id_categoria.nombre if producto.id_categoria else '',
            'is_available': producto.is_available,
            'is_active': producto.is_active
        }
        return JsonResponse(data)
        
    elif request.method == 'PUT':
        try:
            data = json.loads(request.body)
            
            # Actualizar campos básicos
            producto.nombre = data.get('nombre', producto.nombre)
            producto.precio = data.get('precio', producto.precio)
            producto.cantidad = data.get('cantidad', producto.cantidad)
            producto.descripcion = data.get('descripcion', producto.descripcion)
            producto.is_available = data.get('is_available', producto.is_available)
            
            # Actualizar categoría si se proporciona
            if 'id_categoria' in data:
                try:
                    categoria = CategoriaProducto.objects.get(id=data['id_categoria'])
                    producto.id_categoria = categoria
                except CategoriaProducto.DoesNotExist:
                    return JsonResponse({
                        'error': 'Categoría no encontrada'
                    }, status=400)
            
            producto.save()
            
            return JsonResponse({
                'id': producto.id, 
                'nombre': producto.nombre,
                'mensaje': 'Producto actualizado exitosamente'
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'error': 'Formato JSON inválido'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'error': f'Error actualizando producto: {str(e)}'
            }, status=500)
        
    elif request.method == 'DELETE':
        try:
            # Soft delete - marcar como inactivo en lugar de eliminar
            producto.is_active = False
            producto.save()
            
            return JsonResponse({
                'mensaje': f'Producto {producto.nombre} desactivado exitosamente'
            })
            
        except Exception as e:
            return JsonResponse({
                'error': f'Error eliminando producto: {str(e)}'
            }, status=500)


# === FUNCIONES UTILITARIAS PARA CRUD ===

def validar_datos_producto(data):
    """Valida los datos básicos de un producto."""
    errores = []
    
    if not data.get('nombre', '').strip():
        errores.append('El nombre es obligatorio')
    
    try:
        precio = float(data.get('precio', 0))
        if precio <= 0:
            errores.append('El precio debe ser mayor a 0')
    except (ValueError, TypeError):
        errores.append('El precio debe ser un número válido')
    
    try:
        cantidad = int(data.get('cantidad', 0))
        if cantidad < 0:
            errores.append('La cantidad no puede ser negativa')
    except (ValueError, TypeError):
        errores.append('La cantidad debe ser un número entero válido')
    
    return errores


def obtener_productos_activos():
    """Obtiene todos los productos activos con su información básica."""
    return Producto.objects.filter(
        is_active=True
    ).select_related('id_categoria').values(
        'id', 'nombre', 'precio', 'cantidad', 'is_available',
        'id_categoria__nombre', 'descripcion'
    )