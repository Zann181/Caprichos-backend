# core/models.py

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin

# --- Manejador de Usuarios ---
class UsuarioManager(BaseUserManager):
    def create_user(self, email, nombre, password=None, **extra_fields):
        if not email:
            raise ValueError('El campo Email es obligatorio')
        email = self.normalize_email(email)
        user = self.model(email=email, nombre=nombre, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, nombre, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, nombre, password, **extra_fields)

# --- Modelos que Reflejan tu Base de Datos Existente ---

class Rol(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'roles'

    def __str__(self):
        return self.nombre

class Usuario(AbstractBaseUser, PermissionsMixin):
    nombre = models.CharField(max_length=100)
    email = models.EmailField(max_length=100, unique=True)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    # Re-añadimos id_rol para que el modelo coincida con la tabla de la base de datos
    id_rol = models.ForeignKey(Rol, on_delete=models.DO_NOTHING, db_column='id_rol', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    creado_en = models.DateTimeField()
    # El campo last_login que Django espera
    last_login = models.DateTimeField(blank=True, null=True)

    objects = UsuarioManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['nombre']

    class Meta:
        managed = False
        db_table = 'usuarios'

    def __str__(self):
        return self.email

class CategoriaProducto(models.Model):
    nombre = models.CharField(max_length=50, unique=True)
    descripcion = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'categorias_productos'

    def __str__(self):
        return self.nombre

class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.CharField(max_length=500, blank=True, null=True)
    cantidad = models.IntegerField(default=0)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    id_categoria = models.ForeignKey(CategoriaProducto, on_delete=models.DO_NOTHING, db_column='id_categoria')
    tiempo_preparacion = models.IntegerField(default=15)
    imagen_url = models.CharField(max_length=255, blank=True, null=True)
    is_available = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'productos'

    def __str__(self):
        return self.nombre

class Mesa(models.Model):
    numero = models.IntegerField(unique=True)
    capacidad = models.IntegerField()
    ubicacion = models.CharField(max_length=50)
    estado = models.CharField(max_length=20, default='LIBRE')
    is_active = models.BooleanField(default=True)

    class Meta:
        managed = False
        db_table = 'mesas'

    def __str__(self):
        return f"Mesa {self.numero}"

class Orden(models.Model):
    numero_orden = models.CharField(max_length=20, unique=True, blank=True, null=True)
    mesero = models.ForeignKey(Usuario, on_delete=models.DO_NOTHING, db_column='mesero_id')
    mesa = models.ForeignKey(Mesa, on_delete=models.DO_NOTHING, db_column='mesa_id')
    estado = models.CharField(max_length=20, default='NUEVA')
    observaciones = models.CharField(max_length=500, blank=True, null=True)
    creado_en = models.DateTimeField()
    confirmado_en = models.DateTimeField(null=True, blank=True)
    enviado_cocina_en = models.DateTimeField(null=True, blank=True)
    listo_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'ordenes'

    def __str__(self):
        return f"Orden {self.id} - Mesa {self.mesa.numero}"

class OrdenProducto(models.Model):
    orden = models.ForeignKey(Orden, on_delete=models.DO_NOTHING, db_column='orden_id')
    producto = models.ForeignKey(Producto, on_delete=models.DO_NOTHING, db_column='producto_id')
    cantidad = models.IntegerField()
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=20, default='PENDIENTE')
    observaciones = models.CharField(max_length=300, blank=True, null=True)
    listo_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'orden_productos'

    def __str__(self):
        return f"{self.cantidad}x {self.producto.nombre}"

class Factura(models.Model):
    numero_factura = models.CharField(max_length=20, unique=True, blank=True, null=True)
    orden = models.ForeignKey(Orden, on_delete=models.DO_NOTHING, db_column='orden_id')
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)
    impuesto = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    descuento = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(max_length=30, default='PENDIENTE')
    estado_pago = models.CharField(max_length=20, default='NO_PAGADA')
    cliente_nombre = models.CharField(max_length=100, blank=True, null=True)
    cliente_identificacion = models.CharField(max_length=20, blank=True, null=True)
    observaciones = models.CharField(max_length=500, blank=True, null=True)
    creado_en = models.DateTimeField()
    pagado_en = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'facturas'

    def __str__(self):
        return f"Factura para Orden {self.orden.id}"