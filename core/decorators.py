# core/decorators.py

from django.shortcuts import redirect

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