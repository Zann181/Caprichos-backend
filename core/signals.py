# core/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Orden, Factura
from .utils import calcular_total_orden  # ✅ IMPORTAR FUNCIÓN UTILITARIA

@receiver(post_save, sender=Orden)
def crear_o_actualizar_factura(sender, instance, created, **kwargs):
    """
    Se activa cada vez que se guarda una Orden.
    Si el estado de la Orden es 'LISTA', crea su factura si no existe.
    """
    # Solo procesar si la orden está 'LISTA'
    if instance.estado == 'LISTA':
        try:
            # ✅ CORREGIDO: Intentar obtener factura existente primero
            factura = Factura.objects.filter(orden=instance).first()
            
            if not factura:
                # Solo crear si no existe
                total_orden = calcular_total_orden(instance)
                
                Factura.objects.create(
                    orden=instance,
                    subtotal=total_orden,
                    total=total_orden,
                    estado_pago='NO_PAGADA'
                )
                print(f"✅ Factura creada automáticamente para la Orden #{instance.id}")
            else:
                # Si ya existe, solo actualizar el total si es necesario
                total_orden = calcular_total_orden(instance)
                if factura.total != total_orden:
                    factura.subtotal = total_orden
                    factura.total = total_orden
                    factura.save()
                    print(f"✅ Factura actualizada para la Orden #{instance.id}")
                    
        except Exception as e:
            print(f"❌ Error gestionando factura para orden {instance.id}: {str(e)}")