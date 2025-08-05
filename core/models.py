# core/models.py

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

# --- Manejador de Usuarios ---
class UsuarioManager(BaseUserManager):
    def create_user(self, email, nombre, password=None, **extra_fields):
        if not email: raise ValueError('El campo Email es obligatorio')
        email = self.normalize_email(email)
        user = self.model(email=email, nombre=nombre, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    def create_superuser(self, email, nombre, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, nombre, password, **extra_fields)

# --- Modelos del Sistema ---

class Usuario(AbstractBaseUser, PermissionsMixin):
    nombre = models.CharField(max_length=100)
    email = models.EmailField(max_length=100, unique=True)
    telefono = models.CharField(max_length=20, blank=True, null=True) # <-- CORREGIDO
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    creado_en = models.DateTimeField(auto_now_add=True)
    objects = UsuarioManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['nombre']
    def __str__(self): return self.email

class CategoriaProducto(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=255, blank=True, null=True) # <-- CORREGIDO
    is_active = models.BooleanField(default=True) # <-- CORREGIDO
    class Meta:
        verbose_name_plural = "Categorías de Productos"
    def __str__(self): return self.nombre

class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(max_length=500, blank=True, null=True) # <-- CORREGIDO
    cantidad = models.PositiveIntegerField(default=0)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    id_categoria = models.ForeignKey(CategoriaProducto, on_delete=models.PROTECT, related_name='productos')
    tiempo_preparacion = models.PositiveIntegerField(default=15) # <-- CORREGIDO
    imagen_url = models.URLField(max_length=255, blank=True, null=True) # <-- CORREGIDO
    is_available = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True) # <-- CORREGIDO
    def __str__(self): return self.nombre

class Mesa(models.Model):
    numero = models.PositiveIntegerField(unique=True)
    capacidad = models.PositiveIntegerField() # <-- CORREGIDO
    ubicacion = models.CharField(max_length=50) # <-- CORREGIDO
    estado = models.CharField(max_length=20, default='LIBRE')
    is_active = models.BooleanField(default=True) # <-- CORREGIDO
    def __str__(self): return f"Mesa {self.numero}"

class Orden(models.Model):
    numero_orden = models.CharField(max_length=20, unique=True, blank=True, null=True) # <-- CORREGIDO
    mesero = models.ForeignKey(Usuario, on_delete=models.PROTECT, related_name='ordenes')
    mesa = models.ForeignKey(Mesa, on_delete=models.PROTECT)
    estado = models.CharField(max_length=20, default='NUEVA')
    observaciones = models.TextField(blank=True, null=True) # <-- CORREGIDO
    creado_en = models.DateTimeField(auto_now_add=True)
    confirmado_en = models.DateTimeField(null=True, blank=True) # <-- CORREGIDO
    enviado_cocina_en = models.DateTimeField(null=True, blank=True) # <-- CORREGIDO
    listo_en = models.DateTimeField(null=True, blank=True) # <-- CORREGIDO

class OrdenProducto(models.Model):
    orden = models.ForeignKey(Orden, on_delete=models.CASCADE, related_name='productos_ordenados')
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=20, default='PENDIENTE') # <-- CORREGIDO
    observaciones = models.CharField(max_length=300, blank=True, null=True)
    listo_en = models.DateTimeField(null=True, blank=True) # <-- CORREGIDO

class Factura(models.Model):
    numero_factura = models.CharField(max_length=20, unique=True, blank=True, null=True) # <-- CORREGIDO
    orden = models.OneToOneField(Orden, on_delete=models.PROTECT, related_name='factura')
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    impuesto = models.DecimalField(max_digits=10, decimal_places=2, default=0) # <-- CORREGIDO
    descuento = models.DecimalField(max_digits=10, decimal_places=2, default=0) # <-- CORREGIDO
    total = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(max_length=30, blank=True, null=True) # <-- CORREGIDO
    estado_pago = models.CharField(max_length=20, default='NO_PAGADA') # <-- CORREGIDO
    cliente_nombre = models.CharField(max_length=100, blank=True, null=True) # <-- CORREGIDO
    cliente_identificacion = models.CharField(max_length=20, blank=True, null=True) # <-- CORREGIDO
    cliente_telefono = models.CharField(max_length=20, blank=True, null=True) # <-- CORREGIDO
    observaciones = models.TextField(blank=True, null=True) # <-- CORREGIDO
    creado_en = models.DateTimeField(auto_now_add=True)
    pagado_en = models.DateTimeField(null=True, blank=True) # <-- CORREGIDO
    def __str__(self): return f"Factura para Orden #{self.orden.id}"