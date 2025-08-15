# core/views/auth_views.py
"""
Vistas relacionadas con autenticación, autorización y dashboards por rol.
Maneja login, logout, redirección y renderizado de dashboards específicos.
"""

from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.decorators import login_required

from ..forms import CustomAuthenticationForm
from ..decorators import group_required
from ..models import CategoriaProducto, Mesa


# === VISTAS DE AUTENTICACIÓN ===

class UserLoginView(LoginView):
    """Gestiona el inicio de sesión del usuario."""
    template_name = 'login.html'
    form_class = CustomAuthenticationForm
    success_url = reverse_lazy('dashboard')


class UserLogoutView(LogoutView):
    """Gestiona el cierre de sesión del usuario."""
    next_page = reverse_lazy('login')


# === REDIRECCIÓN PRINCIPAL ===

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


# === DASHBOARDS PRINCIPALES ===

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