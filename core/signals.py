# core/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Orden, Factura

@receiver(post_save, sender=Orden)
def crear_o_actualizar_factura(sender, instance, created, **kwargs):
    """
    Se activa cada vez que se guarda una Orden.
    Si el estado de la Orden es 'LISTA', crea su factura si no existe.
    """
    # Si la orden está 'LISTA' y aún no tiene una factura asociada
    if instance.estado == 'LISTA' and not hasattr(instance, 'factura'):
        # Calcula el total de la orden
        total_orden = instance.calcular_total()
        
        # Crea la factura
        Factura.objects.create(
            orden=instance,
            subtotal=total_orden,
            total=total_orden # Inicialmente el total es igual al subtotal
        )
        print(f"Factura creada automáticamente para la Orden #{instance.id}")