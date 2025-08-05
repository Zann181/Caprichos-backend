# core/admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm

# Importamos todos los modelos de nuestra app 'core'
from .models import (
    Usuario, CategoriaProducto, Producto, Mesa, 
    Orden, OrdenProducto, Factura
)


# --- Formularios Personalizados para el Modelo Usuario ---
# Estos formularios le dicen al admin cómo crear y editar usuarios sin el campo 'username'

class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = Usuario
        fields = ('email', 'nombre')

class CustomUserChangeForm(UserChangeForm):
    class Meta:
        model = Usuario
        fields = ('email', 'nombre', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')


# --- Configuraciones Avanzadas del Admin ---

@admin.register(Usuario)
class CustomUserAdmin(UserAdmin):
    """
    Configuración completa para el modelo Usuario en el admin.
    """
    # Usamos nuestros formularios personalizados
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm
    
    # Configuración de la lista de usuarios
    model = Usuario
    list_display = ('email', 'nombre', 'is_staff', 'is_active')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'groups')
    search_fields = ('email', 'nombre')
    ordering = ('email',)
    
    # Campos que se muestran al editar un usuario
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Información Personal', {'fields': ('nombre', 'telefono')}),
        ('Permisos', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Fechas Importantes', {'fields': ('last_login', 'creado_en')}),
    )
    
    # Campos que se muestran al crear un usuario nuevo
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'nombre', 'password', 'password2'),
        }),
    )
    readonly_fields = ('last_login', 'creado_en')

@admin.register(CategoriaProducto)
class CategoriaProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'descripcion', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('nombre',)

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'id_categoria', 'precio', 'cantidad', 'is_available', 'is_active')
    list_filter = ('is_available', 'is_active', 'id_categoria')
    search_fields = ('nombre', 'descripcion')
    list_editable = ('precio', 'cantidad', 'is_available')

@admin.register(Mesa)
class MesaAdmin(admin.ModelAdmin):
    list_display = ('numero', 'ubicacion', 'capacidad', 'estado', 'is_active')
    list_filter = ('estado', 'ubicacion', 'is_active')
    search_fields = ('numero', 'ubicacion')
    list_editable = ('estado',)

class OrdenProductoInline(admin.TabularInline):
    """
    Permite añadir/editar productos directamente desde la vista de una Orden.
    """
    model = OrdenProducto
    extra = 1
    readonly_fields = ('precio_unitario',)

@admin.register(Orden)
class OrdenAdmin(admin.ModelAdmin):
    list_display = ('id', 'mesa', 'mesero', 'estado', 'creado_en')
    list_filter = ('estado', 'mesa', 'mesero')
    search_fields = ('id', 'mesa__numero', 'mesero__nombre')
    readonly_fields = ('creado_en', 'confirmado_en', 'enviado_cocina_en', 'listo_en')
    inlines = [OrdenProductoInline]

@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    list_display = ('id', 'orden', 'total', 'estado_pago', 'creado_en')
    list_filter = ('estado_pago',)
    search_fields = ('orden__id',)
    readonly_fields = ('creado_en', 'pagado_en', 'subtotal', 'total')