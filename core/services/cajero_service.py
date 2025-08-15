# core/services/cajero_service.py
"""
Servicio de negocio para operaciones específicas del cajero.
Contiene toda la lógica relacionada con facturación, pagos y reportes financieros.
"""

from decimal import Decimal
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum, Count, Q, Avg

from ..models import Orden, OrdenProducto, Factura, Mesa, Producto
from ..utils import calcular_total_orden


class CajeroService:
    """Servicio que maneja toda la lógica de negocio específica del cajero."""
    
    def __init__(self):
        self.METODOS_PAGO = [
            'EFECTIVO', 'TARJETA_CREDITO', 'TARJETA_DEBITO', 
            'TRANSFERENCIA', 'DIGITAL', 'MIXTO'
        ]
        self.ESTADOS_PAGO = ['NO_PAGADA', 'PARCIAL', 'PAGADA', 'REEMBOLSADA']
        self.IVA_PORCENTAJE = Decimal('19.0')  # 19% IVA Colombia
    
    # === GESTIÓN DE FACTURAS ===
    
    @transaction.atomic
    def crear_factura_orden(self, orden_id, datos_cliente=None, aplicar_descuento=0, aplicar_iva=True):
        """
        Crea una factura para una orden existente.
        
        Args:
            orden_id: ID de la orden
            datos_cliente: Dict con información del cliente (opcional)
            aplicar_descuento: Descuento en porcentaje (0-100)
            aplicar_iva: Si aplicar IVA o no
            
        Returns:
            dict: Resultado de la operación
        """
        try:
            orden = Orden.objects.get(id=orden_id)
            
            # Verificar que la orden esté lista para facturar
            if orden.estado not in ['LISTA', 'SERVIDA']:
                return {
                    'success': False,
                    'errores': ['La orden debe estar LISTA o SERVIDA para facturar']
                }
            
            # Verificar si ya tiene factura
            if hasattr(orden, 'factura'):
                return {
                    'success': False,
                    'errores': ['La orden ya tiene una factura asociada']
                }
            
            # Calcular totales
            subtotal = calcular_total_orden(orden)
            descuento_amount = subtotal * (Decimal(str(aplicar_descuento)) / 100)
            base_gravable = subtotal - descuento_amount
            
            if aplicar_iva:
                impuesto = base_gravable * (self.IVA_PORCENTAJE / 100)
            else:
                impuesto = Decimal('0')
            
            total = base_gravable + impuesto
            
            # Preparar datos del cliente
            cliente_datos = datos_cliente or {}
            
            # Crear factura
            factura = Factura.objects.create(
                orden=orden,
                subtotal=subtotal,
                descuento=descuento_amount,
                impuesto=impuesto,
                total=total,
                estado_pago='NO_PAGADA',
                cliente_nombre=cliente_datos.get('nombre', ''),
                cliente_identificacion=cliente_datos.get('identificacion', ''),
                cliente_telefono=cliente_datos.get('telefono', ''),
                observaciones=cliente_datos.get('observaciones', '')
            )
            
            # Generar número de factura
            numero_factura = f"FAC-{factura.id:06d}"
            factura.numero_factura = numero_factura
            factura.save()
            
            return {
                'success': True,
                'factura': {
                    'id': factura.id,
                    'numero': numero_factura,
                    'subtotal': float(subtotal),
                    'descuento': float(descuento_amount),
                    'impuesto': float(impuesto),
                    'total': float(total),
                    'estado_pago': factura.estado_pago
                },
                'mensaje': f'Factura {numero_factura} creada exitosamente'
            }
            
        except Orden.DoesNotExist:
            return {
                'success': False,
                'errores': ['Orden no encontrada']
            }
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error creando factura: {str(e)}']
            }
    
    @transaction.atomic
    def procesar_pago_factura(self, factura_id, metodo_pago, monto_pagado, observaciones_pago=""):
        """
        Procesa el pago de una factura.
        
        Args:
            factura_id: ID de la factura
            metodo_pago: Método de pago utilizado
            monto_pagado: Cantidad pagada
            observaciones_pago: Observaciones del pago
            
        Returns:
            dict: Resultado del pago con información del cambio
        """
        try:
            factura = Factura.objects.get(id=factura_id)
            
            # Validar estado de la factura
            if factura.estado_pago == 'PAGADA':
                return {
                    'success': False,
                    'errores': ['La factura ya está pagada']
                }
            
            if factura.estado_pago == 'REEMBOLSADA':
                return {
                    'success': False,
                    'errores': ['No se puede pagar una factura reembolsada']
                }
            
            # Validar método de pago
            if metodo_pago not in self.METODOS_PAGO:
                return {
                    'success': False,
                    'errores': [f'Método de pago inválido. Opciones: {", ".join(self.METODOS_PAGO)}']
                }
            
            # Convertir a Decimal para cálculos exactos
            monto_pagado = Decimal(str(monto_pagado))
            total_factura = factura.total
            
            # Validar monto
            if monto_pagado <= 0:
                return {
                    'success': False,
                    'errores': ['El monto pagado debe ser mayor a 0']
                }
            
            # Calcular cambio
            cambio = monto_pagado - total_factura
            
            # Determinar estado del pago
            if monto_pagado >= total_factura:
                nuevo_estado = 'PAGADA'
                factura.pagado_en = timezone.now()
            else:
                nuevo_estado = 'PARCIAL'
            
            # Actualizar factura
            factura.metodo_pago = metodo_pago
            factura.estado_pago = nuevo_estado
            if observaciones_pago:
                factura.observaciones = f"{factura.observaciones or ''}\nPago: {observaciones_pago}".strip()
            factura.save()
            
            # Si el pago está completo, liberar la mesa
            if nuevo_estado == 'PAGADA':
                orden = factura.orden
                if orden.mesa.numero not in [0, 50]:  # No liberar mesas especiales
                    orden.mesa.estado = 'LIBRE'
                    orden.mesa.save()
            
            resultado = {
                'success': True,
                'pago': {
                    'factura_id': factura.id,
                    'numero_factura': factura.numero_factura,
                    'total_factura': float(total_factura),
                    'monto_pagado': float(monto_pagado),
                    'cambio': float(cambio) if cambio > 0 else 0,
                    'estado_pago': nuevo_estado,
                    'metodo_pago': metodo_pago,
                    'pago_completo': nuevo_estado == 'PAGADA'
                },
                'mensaje': f'Pago procesado exitosamente. Estado: {nuevo_estado}'
            }
            
            if cambio > 0:
                resultado['pago']['mensaje_cambio'] = f'Cambio a entregar: ${cambio:,.2f}'
            elif cambio < 0:
                resultado['pago']['mensaje_faltante'] = f'Falta por pagar: ${abs(cambio):,.2f}'
            
            return resultado
            
        except Factura.DoesNotExist:
            return {
                'success': False,
                'errores': ['Factura no encontrada']
            }
        except (ValueError, TypeError):
            return {
                'success': False,
                'errores': ['Monto de pago inválido']
            }
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error procesando pago: {str(e)}']
            }
    
    @transaction.atomic
    def procesar_reembolso(self, factura_id, motivo_reembolso, monto_reembolso=None):
        """
        Procesa el reembolso de una factura.
        
        Args:
            factura_id: ID de la factura
            motivo_reembolso: Motivo del reembolso
            monto_reembolso: Monto a reembolsar (None = reembolso completo)
        """
        try:
            factura = Factura.objects.get(id=factura_id)
            
            # Validar que la factura esté pagada
            if factura.estado_pago != 'PAGADA':
                return {
                    'success': False,
                    'errores': ['Solo se pueden reembolsar facturas pagadas']
                }
            
            # Determinar monto del reembolso
            if monto_reembolso is None:
                monto_reembolso = factura.total
            else:
                monto_reembolso = Decimal(str(monto_reembolso))
                if monto_reembolso > factura.total:
                    return {
                        'success': False,
                        'errores': ['El monto del reembolso no puede ser mayor al total de la factura']
                    }
            
            # Procesar reembolso
            factura.estado_pago = 'REEMBOLSADA'
            factura.observaciones = f"{factura.observaciones or ''}\nReembolso: {motivo_reembolso} - Monto: ${monto_reembolso}".strip()
            factura.save()
            
            # Actualizar inventario (devolver productos)
            orden = factura.orden
            for producto_orden in orden.productos_ordenados.all():
                producto = producto_orden.producto
                producto.cantidad += producto_orden.cantidad
                producto.save()
            
            return {
                'success': True,
                'reembolso': {
                    'factura_id': factura.id,
                    'numero_factura': factura.numero_factura,
                    'monto_reembolsado': float(monto_reembolso),
                    'motivo': motivo_reembolso
                },
                'mensaje': f'Reembolso procesado: ${monto_reembolso:,.2f}'
            }
            
        except Factura.DoesNotExist:
            return {
                'success': False,
                'errores': ['Factura no encontrada']
            }
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error procesando reembolso: {str(e)}']
            }
    
    # === CONSULTAS Y REPORTES ===
    
    def obtener_facturas_pendientes(self, limite=50):
        """Obtiene facturas pendientes de pago."""
        try:
            facturas = Factura.objects.filter(
                estado_pago__in=['NO_PAGADA', 'PARCIAL']
            ).select_related('orden', 'orden__mesa', 'orden__mesero').order_by('-creado_en')[:limite]
            
            facturas_data = []
            for factura in facturas:
                factura_info = self._formatear_factura_para_cajero(factura)
                facturas_data.append(factura_info)
            
            return {
                'success': True,
                'facturas': facturas_data,
                'total_facturas': len(facturas_data)
            }
            
        except Exception as e:
            return {
                'success': False,
                'errores': [f'Error obteniendo facturas pendientes: {str(e)}']
            }
    
    def obtener_factura_detallada(self, factura_id):
        """Obtiene los detalles completos de una factura."""
        try:
            factura = Factura.objects.select_related(
                'orden', 'orden__mesa', 'orden__mesero'
            ).prefetch_related(
                'orden__productos_ordenados__producto'
            ).get(id=factura_id)