# core/utils.py - Crear este archivo SIN MODIFICAR MODELOS

import json
import time
import hashlib
from django.utils import timezone
from django.core.cache import cache
from datetime import timedelta
from .models import Orden, OrdenProducto, Producto

def generar_hash_estado_cocina():
    """
    Genera un hash del estado actual de la cocina para detectar cambios
    """
    ordenes = Orden.objects.filter(estado__in=['EN_PROCESO', 'NUEVA']).order_by('id')
    
    estado_datos = []
    for orden in ordenes:
        productos = []
        for po in orden.productos_ordenados.all():
            productos.append(f"{po.id}:{po.estado}:{po.cantidad}")
        
        estado_datos.append(f"{orden.id}:{orden.estado}:{':'.join(productos)}")
    
    estado_string = '|'.join(estado_datos)
    return hashlib.md5(estado_string.encode()).hexdigest()

def generar_hash_stock():
    """
    Genera un hash del stock actual para detectar cambios
    """
    productos = Producto.objects.filter(is_active=True).order_by('id')
    stock_string = '|'.join([f"{p.id}:{p.cantidad}" for p in productos])
    return hashlib.md5(stock_string.encode()).hexdigest()


# ✅ ACTUALIZAR: obtener_datos_completos_orden EXISTENTE
def obtener_datos_completos_orden(orden):
    """Obtiene todos los datos de una orden para enviar al frontend"""
    try:
        productos_data = []
        for po in orden.productos_ordenados.all():
            # Detectar si es agregado después
            agregado_despues = po.observaciones and 'AGREGADO_DESPUES' in po.observaciones
            
            # Limpiar observaciones para mostrar
            obs_limpia = ''
            if po.observaciones:
                if 'AGREGADO_DESPUES' in po.observaciones:
                    parts = po.observaciones.split('|')
                    if len(parts) > 1:
                        obs_limpia = parts[1]  # Obtener la observación real
                else:
                    obs_limpia = po.observaciones
            
            productos_data.append({
                'id': po.id,
                'nombre': po.producto.nombre,
                'cantidad': po.cantidad,
                'precio_unitario': float(po.precio_unitario),
                'observaciones': obs_limpia,
                'estado': po.estado,
                'agregado_despues': agregado_despues,
                'listo_en': po.listo_en.isoformat() if po.listo_en else None
            })
        
        # ✅ USAR FUNCIÓN UTILITARIA
        total_orden = calcular_total_orden(orden)
        
        # Obtener nombre del mesero
        mesero_nombre = orden.mesero.nombre if hasattr(orden.mesero, 'nombre') else orden.mesero.username
        
        return {
            'orden_id': orden.id,
            'numero_orden': orden.numero_orden,
            'mesa': {
                'id': orden.mesa.id,
                'numero': orden.mesa.numero,
                'ubicacion': orden.mesa.ubicacion,
                'capacidad': orden.mesa.capacidad
            },
            'mesero': {
                'id': orden.mesero.id,
                'nombre': mesero_nombre,
                'email': orden.mesero.email
            },
            'estado': orden.estado,
            'observaciones': orden.observaciones or '',
            'productos': productos_data,
            'creado_en': orden.creado_en.isoformat(),
            'confirmado_en': orden.confirmado_en.isoformat() if orden.confirmado_en else None,
            'listo_en': orden.listo_en.isoformat() if orden.listo_en else None,
            'total': float(total_orden),
            'completada': all(p['estado'] == 'LISTO' for p in productos_data)
        }
    except Exception as e:
        print(f"Error en obtener_datos_completos_orden: {str(e)}")
        return {
            'orden_id': orden.id if orden else 0,
            'error': str(e),
            'total': 0,
            'productos': [],
            'completada': False
        }


def obtener_todas_ordenes_cocina():
    """
    Obtiene todas las órdenes para la cocina con datos completos
    """
    ordenes = Orden.objects.filter(estado__in=['EN_PROCESO', 'NUEVA']).order_by('creado_en')
    return [obtener_datos_completos_orden(orden) for orden in ordenes]

def obtener_stock_productos():
    """
    Obtiene el stock actual de todos los productos activos
    """
    productos = Producto.objects.filter(is_active=True, is_available=True)
    return {
        str(producto.id): {
            'id': producto.id,
            'nombre': producto.nombre,
            'stock': producto.cantidad,
            'precio': float(producto.precio),
            'categoria': producto.id_categoria.nombre if producto.id_categoria else ''
        } for producto in productos
    }

def long_polling_cocina(hash_anterior=None, timeout=30):
    """
    Long polling para cocina usando hash del estado
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        hash_actual = generar_hash_estado_cocina()
        
        # Si el hash cambió o es la primera vez
        if hash_actual != hash_anterior:
            ordenes = obtener_todas_ordenes_cocina()
            
            # Guardar en cache para debug
            cache.set('ultimo_hash_cocina', hash_actual, 300)  # 5 minutos
            cache.set('ultima_actualizacion_cocina', timezone.now().isoformat(), 300)
            
            return {
                'cambios': True,
                'hash': hash_actual,
                'ordenes': ordenes,
                'timestamp': timezone.now().isoformat()
            }
        
        time.sleep(0.5)  # Verificar cada 500ms
    
    # Timeout - no hubo cambios
    return {
        'cambios': False,
        'hash': hash_anterior,
        'timestamp': timezone.now().isoformat()
    }

def long_polling_meseros(hash_stock_anterior=None, timeout=30):
    """
    Long polling para meseros usando hash del stock
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        hash_stock_actual = generar_hash_stock()
        
        if hash_stock_actual != hash_stock_anterior:
            stock_actual = obtener_stock_productos()
            
            # También verificar órdenes recientes para notificaciones
            ordenes_recientes = Orden.objects.filter(
                creado_en__gte=timezone.now() - timedelta(minutes=5)
            ).order_by('-creado_en')[:5]
            
            ordenes_data = [obtener_datos_completos_orden(orden) for orden in ordenes_recientes]
            
            cache.set('ultimo_hash_stock', hash_stock_actual, 300)
            cache.set('ultima_actualizacion_stock', timezone.now().isoformat(), 300)
            
            return {
                'cambios': True,
                'hash_stock': hash_stock_actual,
                'stock_productos': stock_actual,
                'ordenes_recientes': ordenes_data,
                'timestamp': timezone.now().isoformat()
            }
        
        time.sleep(1)  # Verificar cada segundo para stock
    
    return {
        'cambios': False,
        'hash_stock': hash_stock_anterior,
        'timestamp': timezone.now().isoformat()
    }

def notificar_cambio_cocina():
    """
    Función para forzar notificación a la cocina
    Incrementa un contador en cache para romper el hash
    """
    contador = cache.get('notificacion_cocina', 0)
    cache.set('notificacion_cocina', contador + 1, 300)

def notificar_cambio_stock():
    """
    Función para forzar notificación a meseros
    """
    contador = cache.get('notificacion_stock', 0)
    cache.set('notificacion_stock', contador + 1, 300)

def obtener_estadisticas_sistema():
    """
    Obtiene estadísticas del sistema para debugging
    """
    return {
        'total_ordenes_activas': Orden.objects.filter(estado__in=['EN_PROCESO', 'NUEVA']).count(),
        'productos_activos': Producto.objects.filter(is_active=True).count(),
        'ultimo_hash_cocina': cache.get('ultimo_hash_cocina', 'N/A'),
        'ultimo_hash_stock': cache.get('ultimo_hash_stock', 'N/A'),
        'ultima_act_cocina': cache.get('ultima_actualizacion_cocina', 'N/A'),
        'ultima_act_stock': cache.get('ultima_actualizacion_stock', 'N/A'),
        'timestamp': timezone.now().isoformat()
    }


# core/utils.py - AGREGAR ESTA FUNCIÓN AL ARCHIVO EXISTENTE

def calcular_total_orden(orden):
    """
    Función utilitaria para calcular el total de una orden
    Reemplaza el método calcular_total() que no existe en el modelo
    """
    try:
        total = sum(
            item.cantidad * item.precio_unitario 
            for item in orden.productos_ordenados.all()
        )
        return total
    except Exception as e:
        print(f"Error calculando total de orden {orden.id}: {str(e)}")
        return 0
