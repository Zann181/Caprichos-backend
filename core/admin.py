# core/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Rol, Usuario, CategoriaProducto, Producto, Mesa, Orden, OrdenProducto, Factura

class CustomUserAdmin(BaseUserAdmin):
    # Usa la configuración de UserAdmin pero con nuestro modelo Usuario
    model = Usuario
    list_display = ('email', 'nombre', 'id_rol', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups', 'id_rol')
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('nombre', 'telefono', 'id_rol')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login',)}),
    )
    search_fields = ('email', 'nombre')
    ordering = ('email',)

class OrdenProductoInline(admin.TabularInline):
    # Permite añadir productos directamente al crear/editar una orden
    model = OrdenProducto
    extra = 1 # Cuántos campos vacíos mostrar

@admin.register(Orden)
class OrdenAdmin(admin.ModelAdmin):
    list_display = ('id', 'mesa', 'mesero', 'estado', 'creado_en')
    list_filter = ('estado', 'mesa', 'mesero')
    inlines = [OrdenProductoInline]

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'id_categoria', 'precio', 'cantidad', 'is_available')
    list_filter = ('id_categoria', 'is_available')
    search_fields = ('nombre',)

@admin.register(Mesa)
class MesaAdmin(admin.ModelAdmin):
    list_display = ('numero', 'ubicacion', 'capacidad', 'estado')
    list_filter = ('estado', 'ubicacion')

# Registro de los modelos en el panel de admin
admin.site.register(Usuario, CustomUserAdmin)
admin.site.register(Rol)
admin.site.register(CategoriaProducto)
admin.site.register(Factura)