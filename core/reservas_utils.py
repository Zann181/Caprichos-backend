# core/reservas_utils.py - CREAR ESTE NUEVO ARCHIVO
"""
Sistema de reservas usando las tablas existentes sin modificar modelos.
Usa las observaciones de Orden para manejar reservas.
"""

from django.utils import timezone
from django.db import transaction
from datetime import datetime, timedelta
from .models import Mesa, Orden, Usuario
import json

# === CONSTANTES PARA RESERVAS ===
MESA_DOMICILIO = 0
MESA_LLEVAR = 50

class ReservasManager:
    """Gestor de reservas usando la infraestructura existente"""
    
    @staticmethod
    def crear_mesas_especiales():
        """Crear mesas especiales 0 y 50 si no existen"""
        try:
            # Mesa 0 para domicilios
            mesa_domicilio, created = Mesa.objects.get_or_create(
                numero=MESA_DOMICILIO,
                defaults={
                    'ubicacion': 'Domicilio',
                    'capacidad': 99,
                    'estado': 'LIBRE',  # Siempre libre para nuevas órdenes
                    'is_active': True
                }
            )
            
            # Mesa 50 para llevar
            mesa_llevar, created = Mesa.objects.get_or_create(
                numero=MESA_LLEVAR,
                defaults={
                    'ubicacion': 'Para Llevar',
                    'capacidad': 99,
                    'estado': 'LIBRE',  # Siempre libre para nuevas órdenes
                    'is_active': True
                }
            )
            
            return mesa_domicilio, mesa_llevar
            
        except Exception as e:
            print(f"Error creando mesas especiales: {e}")
            return None, None
    
    @staticmethod
    def crear_reserva(datos_reserva, creado_por):
        """
        Crear una reserva usando el sistema de órdenes existente.
        Estructura de datos_reserva:
        {
            'tipo': 'MESA' | 'DOMICILIO' | 'LLEVATE',
            'cliente_nombre': str,
            'cliente_telefono': str,
            'cliente_email': str (opcional),
            'fecha_reserva': datetime,
            'mesa_id': int (para reservas de mesa),
            'personas': int,
            'direccion_entrega': str (para domicilios),
            'observaciones': str (opcional),
            'productos_preordenados': list (opcional)
        }
        """
        try:
            with transaction.atomic():
                # Determinar mesa según tipo
                if datos_reserva['tipo'] == 'DOMICILIO':
                    mesa = Mesa.objects.get(numero=MESA_DOMICILIO)
                elif datos_reserva['tipo'] == 'LLEVATE':
                    mesa = Mesa.objects.get(numero=MESA_LLEVAR)
                else:  # MESA
                    mesa = Mesa.objects.get(id=datos_reserva['mesa_id'])
                
                # Validar disponibilidad para mesas normales
                if datos_reserva['tipo'] == 'MESA':
                    if ReservasManager.mesa_reservada_en_fecha(mesa, datos_reserva['fecha_reserva']):
                        raise ValueError(f"La mesa {mesa.numero} ya está reservada para esa fecha/hora")
                
                # Crear datos de reserva en JSON para observaciones
                reserva_info = {
                    'es_reserva': True,
                    'tipo_reserva': datos_reserva['tipo'],
                    'cliente_nombre': datos_reserva['cliente_nombre'],
                    'cliente_telefono': datos_reserva['cliente_telefono'],
                    'cliente_email': datos_reserva.get('cliente_email', ''),
                    'fecha_reserva': datos_reserva['fecha_reserva'].isoformat(),
                    'personas': datos_reserva.get('personas', 1),
                    'direccion_entrega': datos_reserva.get('direccion_entrega', ''),
                    'estado_reserva': 'PENDIENTE',
                    'creado_por': creado_por.id,
                    'requiere_confirmacion': True
                }
                
                # Combinar observaciones
                observaciones_generales = datos_reserva.get('observaciones', '')
                if observaciones_generales:
                    reserva_info['observaciones_cliente'] = observaciones_generales
                
                # Crear orden como reserva
                nueva_reserva = Orden.objects.create(
                    mesa=mesa,
                    mesero=creado_por,
                    estado='NUEVA',  # Estado especial para reservas
                    observaciones=f"RESERVA:{json.dumps(reserva_info)}"
                )
                
                # Generar número de reserva
                numero_reserva = f"R-{nueva_reserva.id:06d}"
                reserva_info['numero_reserva'] = numero_reserva
                nueva_reserva.observaciones = f"RESERVA:{json.dumps(reserva_info)}"
                nueva_reserva.save()
                
                return nueva_reserva, numero_reserva
                
        except Exception as e:
            raise ValueError(f"Error creando reserva: {str(e)}")
    
    @staticmethod
    def obtener_reservas(filtros=None):
        """Obtener todas las reservas del sistema"""
        # Buscar órdenes que tengan 'RESERVA:' en observaciones
        ordenes_reserva = Orden.objects.filter(
            observaciones__startswith='RESERVA:'
        ).order_by('-creado_en')
        
        reservas = []
        for orden in ordenes_reserva:
            try:
                reserva_data = ReservasManager.extraer_datos_reserva(orden)
                if reserva_data:
                    # Aplicar filtros si existen
                    if filtros:
                        if filtros.get('estado') and reserva_data.get('estado_reserva') != filtros['estado']:
                            continue
                        if filtros.get('tipo') and reserva_data.get('tipo_reserva') != filtros['tipo']:
                            continue
                        if filtros.get('mesero_id') and orden.mesero.id != filtros['mesero_id']:
                            continue
                    
                    reservas.append({
                        'orden_id': orden.id,
                        'reserva_data': reserva_data,
                        'mesa': {
                            'id': orden.mesa.id,
                            'numero': orden.mesa.numero,
                            'ubicacion': orden.mesa.ubicacion
                        },
                        'mesero': {
                            'id': orden.mesero.id,
                            'nombre': orden.mesero.nombre
                        },
                        'creado_en': orden.creado_en.isoformat()
                    })
            except:
                continue
        
        return reservas
    
    @staticmethod
    def extraer_datos_reserva(orden):
        """Extraer datos de reserva de las observaciones de una orden"""
        try:
            if not orden.observaciones or not orden.observaciones.startswith('RESERVA:'):
                return None
            
            json_data = orden.observaciones[8:]  # Remover 'RESERVA:'
            return json.loads(json_data)
        except:
            return None
    
    @staticmethod
    def actualizar_estado_reserva(orden_id, nuevo_estado):
        """Actualizar el estado de una reserva"""
        try:
            orden = Orden.objects.get(id=orden_id)
            reserva_data = ReservasManager.extraer_datos_reserva(orden)
            
            if not reserva_data:
                raise ValueError("No es una reserva válida")
            
            reserva_data['estado_reserva'] = nuevo_estado
            
            # Actualizar timestamps según estado
            if nuevo_estado == 'CONFIRMADA':
                reserva_data['confirmado_en'] = timezone.now().isoformat()
            elif nuevo_estado == 'EN_CURSO':
                reserva_data['iniciado_en'] = timezone.now().isoformat()
                # Para mesas normales, marcar como ocupada
                if orden.mesa.numero not in [MESA_DOMICILIO, MESA_LLEVAR]:
                    orden.mesa.estado = 'OCUPADA'
                    orden.mesa.save()
            elif nuevo_estado == 'COMPLETADA':
                reserva_data['completado_en'] = timezone.now().isoformat()
                # Liberar mesa si no es especial
                if orden.mesa.numero not in [MESA_DOMICILIO, MESA_LLEVAR]:
                    orden.mesa.estado = 'LIBRE'
                    orden.mesa.save()
            
            orden.observaciones = f"RESERVA:{json.dumps(reserva_data)}"
            orden.save()
            
            return True
            
        except Exception as e:
            print(f"Error actualizando reserva: {e}")
            return False
    
    @staticmethod
    def mesa_reservada_en_fecha(mesa, fecha_reserva):
        """Verificar si una mesa está reservada en una fecha específica"""
        # Buscar reservas activas en esa mesa
        fecha_inicio = fecha_reserva - timedelta(hours=2)
        fecha_fin = fecha_reserva + timedelta(hours=2)
        
        reservas_existentes = Orden.objects.filter(
            mesa=mesa,
            observaciones__startswith='RESERVA:',
            creado_en__range=[fecha_inicio, fecha_fin]
        )
        
        for orden in reservas_existentes:
            reserva_data = ReservasManager.extraer_datos_reserva(orden)
            if reserva_data and reserva_data.get('estado_reserva') in ['PENDIENTE', 'CONFIRMADA', 'EN_CURSO']:
                return True
        
        return False
    
    @staticmethod
    def obtener_mesas_disponibles_para_reserva(fecha_reserva):
        """Obtener mesas disponibles para una fecha específica"""
        mesas_disponibles = []
        
        # Siempre incluir mesas especiales
        mesa_domicilio = Mesa.objects.filter(numero=MESA_DOMICILIO).first()
        mesa_llevar = Mesa.objects.filter(numero=MESA_LLEVAR).first()
        
        if mesa_domicilio:
            mesas_disponibles.append({
                'id': mesa_domicilio.id,
                'numero': mesa_domicilio.numero,
                'ubicacion': mesa_domicilio.ubicacion,
                'tipo': 'DOMICILIO',
                'siempre_disponible': True
            })
        
        if mesa_llevar:
            mesas_disponibles.append({
                'id': mesa_llevar.id,
                'numero': mesa_llevar.numero,
                'ubicacion': mesa_llevar.ubicacion,
                'tipo': 'LLEVATE',
                'siempre_disponible': True
            })
        
        # Verificar mesas normales
        mesas_normales = Mesa.objects.filter(
            is_active=True
        ).exclude(
            numero__in=[MESA_DOMICILIO, MESA_LLEVAR]
        )
        
        for mesa in mesas_normales:
            if not ReservasManager.mesa_reservada_en_fecha(mesa, fecha_reserva):
                mesas_disponibles.append({
                    'id': mesa.id,
                    'numero': mesa.numero,
                    'ubicacion': mesa.ubicacion,
                    'capacidad': mesa.capacidad,
                    'tipo': 'MESA',
                    'siempre_disponible': False
                })
        
        return mesas_disponibles
    
    @staticmethod
    def convertir_reserva_a_orden(orden_id, mesero=None):
        """Convertir una reserva confirmada en una orden activa"""
        try:
            with transaction.atomic():
                orden = Orden.objects.get(id=orden_id)
                reserva_data = ReservasManager.extraer_datos_reserva(orden)
                
                if not reserva_data:
                    raise ValueError("No es una reserva válida")
                
                if reserva_data.get('estado_reserva') != 'CONFIRMADA':
                    raise ValueError("La reserva debe estar confirmada")
                
                # Actualizar estado a EN_CURSO
                reserva_data['estado_reserva'] = 'EN_CURSO'
                reserva_data['iniciado_en'] = timezone.now().isoformat()
                
                # Cambiar estado de orden
                orden.estado = 'EN_PROCESO'
                if mesero:
                    orden.mesero = mesero
                
                # Ocupar mesa si es necesario
                if orden.mesa.numero not in [MESA_DOMICILIO, MESA_LLEVAR]:
                    orden.mesa.estado = 'OCUPADA'
                    orden.mesa.save()
                
                # Actualizar observaciones para mantener info de reserva
                orden.observaciones = f"RESERVA:{json.dumps(reserva_data)}"
                orden.save()
                
                return orden
                
        except Exception as e:
            raise ValueError(f"Error convirtiendo reserva: {str(e)}")

# === INICIALIZACIÓN ===
def inicializar_sistema_reservas():
    """Inicializar el sistema de reservas creando mesas especiales"""
    try:
        mesa_domicilio, mesa_llevar = ReservasManager.crear_mesas_especiales()
        
        if mesa_domicilio and mesa_llevar:
            print("✅ Sistema de reservas inicializado correctamente")
            print(f"   - Mesa {MESA_DOMICILIO}: Domicilios")
            print(f"   - Mesa {MESA_LLEVAR}: Para Llevar")
            return True
        else:
            print("❌ Error inicializando sistema de reservas")
            return False
            
    except Exception as e:
        print(f"❌ Error en inicialización: {e}")
        return False