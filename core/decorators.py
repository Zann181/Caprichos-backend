# core/decorators.py

from django.shortcuts import redirect


import time
import hashlib
from functools import wraps
from django.http import JsonResponse
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
import json

def group_required(allowed_groups=[]):
    """
    Decorador que verifica si un usuario pertenece a uno de los grupos permitidos.
    """
    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            # 1. Si el usuario no está autenticado, lo enviamos al login.
            if not request.user.is_authenticated:
                return redirect('login')
            
            # 2. Si el usuario es un superusuario, siempre tiene acceso.
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            # 3. Si el usuario pertenece a alguno de los grupos en la lista, le damos acceso.
            if request.user.groups.filter(name__in=allowed_groups).exists():
                return view_func(request, *args, **kwargs)
            else:
                # 4. Si no cumple ninguna condición, no tiene permiso.
                return redirect('acceso_denegado')
        return wrapper
    return decorator


# core/decorators.py - AGREGAR ESTAS NUEVAS FUNCIONES AL ARCHIVO EXISTENTE

import time
import hashlib
from functools import wraps
from django.http import JsonResponse
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
import json

# === CONFIGURACIÓN DEL SISTEMA DE DEBOUNCE ===
DEBOUNCE_CONFIG = {
    'DEFAULT_DELAY': 0.5,      # 500ms por defecto
    'CRITICAL_DELAY': 2.0,     # 2 segundos para operaciones críticas
    'FORM_DELAY': 1.0,         # 1 segundo para formularios
    'MAX_CACHE_TIME': 300,     # 5 minutos máximo en cache
    'CACHE_PREFIX': 'debounce_'
}

def generate_debounce_key(user_id, view_name, request_data=None):
    """
    Genera una clave única para el debounce basada en:
    - ID del usuario
    - Nombre de la vista
    - Datos de la request (opcional)
    """
    base_string = f"{user_id}:{view_name}"
    
    if request_data:
        # Crear hash de los datos para incluir en la clave
        data_string = json.dumps(request_data, sort_keys=True)
        data_hash = hashlib.md5(data_string.encode()).hexdigest()[:8]
        base_string += f":{data_hash}"
    
    return f"{DEBOUNCE_CONFIG['CACHE_PREFIX']}{base_string}"

def debounce_request(delay=None, include_data=False, critical=False, error_message=None):
    """
    Decorador para prevenir requests duplicados en el backend.
    
    Args:
        delay: Tiempo en segundos para el debounce (por defecto usa DEBOUNCE_CONFIG)
        include_data: Si incluir los datos del request en la clave del debounce
        critical: Si es una operación crítica (usa CRITICAL_DELAY)
        error_message: Mensaje personalizado de error
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Determinar el delay
            if delay is not None:
                debounce_delay = delay
            elif critical:
                debounce_delay = DEBOUNCE_CONFIG['CRITICAL_DELAY']
            else:
                debounce_delay = DEBOUNCE_CONFIG['DEFAULT_DELAY']
            
            # Obtener el usuario (si está autenticado)
            user_id = request.user.id if request.user.is_authenticated else request.session.session_key
            if not user_id:
                # Si no hay usuario ni sesión, crear una clave temporal
                user_id = f"anonymous_{request.META.get('REMOTE_ADDR', 'unknown')}"
            
            # Obtener datos del request si se solicita
            request_data = None
            if include_data:
                if request.method == 'POST':
                    try:
                        request_data = json.loads(request.body.decode('utf-8'))
                    except:
                        request_data = dict(request.POST)
                elif request.method == 'GET':
                    request_data = dict(request.GET)
            
            # Generar clave de debounce
            debounce_key = generate_debounce_key(user_id, view_func.__name__, request_data)
            
            # Verificar si hay una request reciente
            last_request_time = cache.get(debounce_key)
            current_time = time.time()
            
            if last_request_time:
                time_since_last = current_time - last_request_time
                if time_since_last < debounce_delay:
                    # Request muy rápida, bloquear
                    remaining_time = debounce_delay - time_since_last
                    
                    default_message = f"⚠️ Operación muy rápida. Espera {remaining_time:.1f} segundos antes de intentar nuevamente."
                    response_message = error_message or default_message
                    
                    return JsonResponse({
                        'error': response_message,
                        'debounce_remaining': round(remaining_time, 1),
                        'retry_after': round(remaining_time, 1)
                    }, status=429)  # Too Many Requests
            
            # Guardar timestamp actual en cache
            cache.set(debounce_key, current_time, timeout=DEBOUNCE_CONFIG['MAX_CACHE_TIME'])
            
            # Ejecutar la vista original
            try:
                return view_func(request, *args, **kwargs)
            except Exception as e:
                # Si hay error, limpiar el cache para permitir reintento inmediato
                cache.delete(debounce_key)
                raise e
        
        return wrapper
    return decorator

def debounce_user_action(action_name, user_id, delay=None, data=None):
    """
    Función utilitaria para verificar debounce manualmente en las vistas.
    
    Returns:
        tuple: (is_allowed: bool, remaining_time: float)
    """
    if delay is None:
        delay = DEBOUNCE_CONFIG['DEFAULT_DELAY']
    
    debounce_key = generate_debounce_key(user_id, action_name, data)
    last_action_time = cache.get(debounce_key)
    current_time = time.time()
    
    if last_action_time:
        time_since_last = current_time - last_action_time
        if time_since_last < delay:
            return False, delay - time_since_last
    
    # Permitir la acción y guardar timestamp
    cache.set(debounce_key, current_time, timeout=DEBOUNCE_CONFIG['MAX_CACHE_TIME'])
    return True, 0

def clear_user_debounces(user_id):
    """Limpia todos los debounces de un usuario específico."""
    # Nota: Esto requiere una implementación más compleja para buscar todas las claves
    # Por simplicidad, se puede llamar cuando el usuario cierre sesión
    pass

# === DECORADOR ESPECÍFICO PARA OPERACIONES CRÍTICAS ===
def critical_operation(delay=None, error_message=None):
    """Decorador para operaciones críticas como crear órdenes, procesar pagos, etc."""
    return debounce_request(
        delay=delay or DEBOUNCE_CONFIG['CRITICAL_DELAY'],
        include_data=True,
        critical=True,
        error_message=error_message or "⚠️ Operación en proceso. No envíes múltiples requests."
    )

# === DECORADOR PARA FORMULARIOS ===
def form_debounce(delay=None):
    """Decorador específico para envío de formularios."""
    return debounce_request(
        delay=delay or DEBOUNCE_CONFIG['FORM_DELAY'],
        include_data=True,
        error_message="📝 Formulario enviado recientemente. Espera un momento antes de enviar nuevamente."
    )

# === MIDDLEWARE PARA DEBOUNCE GLOBAL (OPCIONAL) ===
class DebounceMiddleware:
    """
    Middleware que aplica debounce automático a todas las requests POST.
    USAR CON CUIDADO - Solo para aplicaciones específicas.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Aplicar debounce solo a requests POST de usuarios autenticados
        if (request.method == 'POST' and 
            request.user.is_authenticated and 
            not request.path.startswith('/admin/')):  # Excluir admin
            
            user_id = request.user.id
            view_name = request.resolver_match.view_name if request.resolver_match else 'unknown'
            
            # Verificar debounce
            debounce_key = generate_debounce_key(user_id, f"global_{view_name}")
            last_request_time = cache.get(debounce_key)
            current_time = time.time()
            
            if last_request_time and (current_time - last_request_time) < 0.5:  # 500ms global
                return JsonResponse({
                    'error': '⚠️ Requests muy rápidas. Reduce la velocidad.',
                    'global_debounce': True
                }, status=429)
            
            cache.set(debounce_key, current_time, timeout=60)  # 1 minuto
        
        return self.get_response(request)

