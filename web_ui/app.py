from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask import session
import json, os, sys
import requests
from functools import wraps
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'clave-secreta-para-flash-change-in-production')

# API URLs (configurables via env vars)
AUTH_API = os.getenv('AUTH_API', 'http://auth_api:8000')
SLICE_MANAGER_API = os.getenv('SLICE_MANAGER_API', 'http://slice_manager_api:5900')
DRIVERS_API = os.getenv('DRIVERS_API', 'http://drivers:5003')
IMAGE_MANAGER_API = os.getenv('IMAGE_MANAGER_API', 'http://image_manager_api:5007')

# Configuración de base de datos para slices
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'slices_db'),
    'user': os.getenv('DB_USER', 'slices_user'),
    'password': os.getenv('DB_PASSWORD', 'slices_pass123'),
    'database': os.getenv('DB_NAME', 'slices_db')
}

# Configuración de base de datos para security groups
SG_DB_CONFIG = {
    'host': os.getenv('SG_DB_HOST', 'security_groups_db'),
    'user': os.getenv('SG_DB_USER', 'secgroups_user'),
    'password': os.getenv('SG_DB_PASSWORD', 'secgroups_pass123'),
    'database': os.getenv('SG_DB_NAME', 'security_groups_db')
}

# Decorador para proteger rutas que requieren autenticación
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'token' not in session:
            # Si es una petición AJAX/API, devolver JSON
            if request.path.startswith('/api/'):
                return jsonify({
                    'success': False,
                    'message': 'Sesión expirada. Debes iniciar sesión.'
                }), 401
            # Si es una petición normal, redirigir al login
            flash('Debes iniciar sesión para acceder a esta página.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Función para verificar si el token expiró
def check_token_expiration(response_data):
    """
    Verifica si la respuesta indica token expirado.
    Retorna True si el token expiró, False en caso contrario.
    """
    if isinstance(response_data, dict):
        detail = response_data.get('detail', '')
        message = response_data.get('message', '')
        
        # Convertir a string si no lo es
        if not isinstance(detail, str):
            detail = str(detail) if detail else ''
        if not isinstance(message, str):
            message = str(message) if message else ''
        
        detail_lower = detail.lower()
        message_lower = message.lower()
        
        if 'token expirado' in detail_lower or 'token expired' in detail_lower:
            return True
        if 'token expirado' in message_lower or 'token expired' in message_lower:
            return True
        if 'unauthorized' in detail_lower and 'token' in detail_lower:
            return True
    
    return False

def handle_api_response(response):
    """
    Maneja respuestas de APIs y verifica expiración de token.
    Si el token expiró, cierra la sesión y redirige al login.
    """
    try:
        data = response.json()
    except:
        data = {}
    
    # Verificar si el token expiró
    if response.status_code == 401 or check_token_expiration(data):
        session.clear()
        flash('Tu sesión ha expirado. Por favor, inicia sesión nuevamente.', 'warning')
        return None, True  # None data, expired=True
    
    return data, False  # data, expired=False

# --- LOGIN ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        correo = request.form.get('username')  # El form usa 'username' pero enviaremos como 'correo'
        password = request.form.get('password')
        
        try:
            # Llamar a auth_api para autenticación
            response = requests.post(
                f'{AUTH_API}/login',
                json={
                    'correo': correo,
                    'password': password
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                # Guardar token y datos del usuario en la sesión
                session['token'] = data['token']
                session['user'] = data['user_info']['correo']
                session['user_id'] = data['user_info']['id']
                session['nombre_completo'] = f"{data['user_info']['nombre']} {data['user_info']['apellidos']}"
                session['role'] = data['user_info']['rol']
                
                flash('Inicio de sesión exitoso', 'success')
                return redirect(url_for('index'))
            
            elif response.status_code == 401:
                error = 'Usuario o contraseña incorrectos.'
            else:
                error = 'Error al conectar con el servidor de autenticación.'
                
        except requests.exceptions.ConnectionError:
            error = 'No se pudo conectar con el servidor de autenticación.'
        except requests.exceptions.Timeout:
            error = 'Tiempo de espera agotado al intentar autenticar.'
        except Exception as e:
            error = f'Error inesperado: {str(e)}'
    
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada exitosamente', 'info')
    return redirect(url_for('login'))

# --- INDEX (Lista de Slices) ---
@app.route('/')
@login_required
def index():
    # Esta ruta solo renderiza el template
    # Los slices se cargarán via AJAX desde JavaScript
    return render_template('index.html')

@app.route('/api/slices/list')
@login_required
def api_list_slices():
    """Endpoint AJAX para obtener lista de slices"""
    try:
        # Llamar a slice_manager_api con el token del usuario
        headers = {
            'Authorization': f"Bearer {session.get('token')}"
        }
        
        response = requests.get(
            f'{SLICE_MANAGER_API}/slices/list',
            headers=headers,
            timeout=10
        )
        
        # Verificar si el token expiró
        data, expired = handle_api_response(response)
        if expired:
            return jsonify({
                'success': False,
                'expired': True,
                'message': 'Sesión expirada'
            }), 401
        
        if response.status_code == 200:
            return jsonify(data)
        else:
            return jsonify({
                'success': False,
                'message': data.get('detail', 'Error al obtener slices')
            }), response.status_code
            
    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'message': 'No se pudo conectar con el servicio de slices'
        }), 503
    except requests.exceptions.Timeout:
        return jsonify({
            'success': False,
            'message': 'Tiempo de espera agotado'
        }), 504
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error inesperado: {str(e)}'
        }), 500

@app.route('/favicon.ico')
def favicon():
    try:
        return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico')
    except Exception:
        return ('', 204)

# --- CREAR SLICE ---
@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_slice():
    if request.method == 'POST':
        # Recibir datos del editor visual
        if request.is_json:
            payload = request.get_json()
        else:
            slice_data = request.form.get('slice_data')
            if slice_data:
                payload = json.loads(slice_data)
            else:
                return jsonify({'success': False, 'message': 'No se recibieron datos'}), 400
        
        # Log del JSON generado para verificación
        print("="*80)
        print("JSON DE SLICE GENERADO:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print("="*80)
        sys.stdout.flush()
        
        # Llamada a API para crear slice
        try:
            token = session.get('token')
            
            if not token:
                return jsonify({
                    'success': False,
                    'message': 'Sesión expirada. Por favor inicie sesión nuevamente.'
                }), 401
            
            response = requests.post(
                f'{SLICE_MANAGER_API}/slices/create',
                json=payload,
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                },
                timeout=60
            )
            
            if response.status_code == 200 or response.status_code == 201:
                result = response.json()
                return jsonify({
                    'success': True,
                    'message': f"Slice '{payload.get('nombre_slice')}' creado y desplegado exitosamente",
                    'data': result
                })
            elif response.status_code == 401:
                return jsonify({
                    'success': False,
                    'message': 'Token inválido o expirado. Por favor cierre sesión e inicie sesión nuevamente.'
                }), 401
            else:
                try:
                    error_data = response.json()
                    error_msg = error_data.get('detail', error_data.get('message', 'Error desconocido'))
                except:
                    error_msg = response.text
                    
                return jsonify({
                    'success': False,
                    'message': f'Error al crear slice: {error_msg}'
                }), response.status_code
                
        except requests.exceptions.Timeout:
            return jsonify({
                'success': False,
                'message': 'Timeout: El despliegue está tomando más tiempo del esperado'
            }), 504
        except requests.exceptions.RequestException as e:
            return jsonify({
                'success': False,
                'message': f'Error de conexión con Slice Manager: {str(e)}'
            }), 503
    
    return render_template('create.html')

# --- DETALLE DE SLICE ---
@app.route('/slice/<int:slice_id>')
@login_required
def slice_detail(slice_id):
    return render_template('detail.html', slice_id=slice_id)

@app.route('/api/slice/<int:slice_id>')
@login_required
def api_slice_detail(slice_id):
    """Obtener detalle del slice directamente desde la base de datos"""
    print(f"DEBUG: api_slice_detail llamado con slice_id={slice_id}", file=sys.stderr)
    
    try:
        # Conectar a la base de datos de slices
        connection = mysql.connector.connect(**DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener el slice con su peticion_json
        cursor.execute("SELECT * FROM slices WHERE id = %s", (slice_id,))
        slice_data = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        if not slice_data:
            print(f"DEBUG: Slice {slice_id} no encontrado en la BD", file=sys.stderr)
            return jsonify({
                'success': False,
                'message': f'Slice {slice_id} no encontrado'
            }), 404
        
        # Convertir peticion_json de string a dict si es necesario
        if isinstance(slice_data['peticion_json'], str):
            slice_data['peticion_json'] = json.loads(slice_data['peticion_json'])
        
        # Convertir vms de string a dict si es necesario
        if isinstance(slice_data.get('vms'), str):
            slice_data['vms'] = json.loads(slice_data['vms'])
        
        print(f"DEBUG: Slice encontrado: {slice_data['nombre_slice']}", file=sys.stderr)
        return jsonify(slice_data)
        
    except Error as e:
        print(f"DEBUG: Error de BD: {str(e)}", file=sys.stderr)
        return jsonify({
            'success': False,
            'message': f'Error de base de datos: {str(e)}'
        }), 500
    except Exception as e:
        print(f"DEBUG: Error general: {str(e)}", file=sys.stderr)
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        }), 500

# --- EDITAR SLICE ---
@app.route('/slice/<slice_name>/edit', methods=['GET', 'POST'])
@login_required
def edit_slice(slice_name):
    if request.method == 'POST':
        slice_data = request.form.get('slice_data')
        if slice_data:
            payload = json.loads(slice_data)
            
            # TODO: Llamada a API para actualizar slice
            # PUT {SLICE_MANAGER_API}/slices/{slice_name}
            
            flash(f"Slice '{slice_name}' actualizado exitosamente ✅")
            return redirect(url_for('slice_detail', slice_name=slice_name))
    
    return render_template('edit.html', slice_name=slice_name)

@app.route('/update/<slice_name>', methods=['POST'])
@login_required
def update_slice(slice_name):
    slice_data = request.form.get('slice_data')
    if slice_data:
        payload = json.loads(slice_data)
        
        # TODO: Llamada a API para actualizar slice
        # PUT {SLICE_MANAGER_API}/slices/{slice_name}
        
        flash(f"Slice '{slice_name}' actualizado exitosamente ✅")
    
    return redirect(url_for('slice_detail', slice_name=slice_name))

# --- ELIMINAR SLICE ---
@app.route('/delete/<int:slice_id>', methods=['POST'])
@login_required
def delete_slice(slice_id):
    """Eliminar un slice llamando al Slice Manager API"""
    try:
        token = session.get('token')
        
        # Llamar al Slice Manager para eliminar el slice
        response = requests.post(
            f'{SLICE_MANAGER_API}/slices/delete/{slice_id}',
            headers={
                'Authorization': f'Bearer {token}'
            },
            timeout=120
        )
        
        if response.status_code == 200:
            data = response.json()
            flash(f"Slice eliminado exitosamente ✅", 'success')
        else:
            error_data = response.json() if response.headers.get('content-type') == 'application/json' else {'detail': response.text}
            flash(f"Error al eliminar slice: {error_data.get('detail', 'Error desconocido')}", 'error')
            
    except requests.exceptions.Timeout:
        flash('Error: Timeout al eliminar el slice. El proceso puede estar en curso.', 'warning')
    except requests.exceptions.RequestException as e:
        flash(f'Error de conexión al eliminar slice: {str(e)}', 'error')
    except Exception as e:
        flash(f'Error inesperado: {str(e)}', 'error')
    
    return redirect(url_for('index'))

# --- SLICES ELIMINADOS ---
@app.route('/deleted')
@login_required
def deleted_slices():
    deleted = []
    
    # TODO: Llamada a API para obtener slices eliminados (si aplica)
    
    return render_template('deleted.html', slices=deleted)

@app.route('/restore/<slice_name>', methods=['POST'])
@login_required
def restore_slice(slice_name):
    # TODO: Llamada a API para restaurar slice (si aplica)
    
    flash(f"Slice '{slice_name}' restaurado exitosamente ✅", 'success')
    return redirect(url_for('index'))

# --- API HELPERS ---
@app.route('/api/next-slice-name')
@login_required
def next_slice_name():
    # TODO: Llamada a API para obtener siguiente nombre de slice
    # O generar localmente basado en conteo
    
    return jsonify({
        'success': True,
        'name': 'slice-1'
    })

# --- SECURITY GROUPS ---
@app.route('/security-groups', methods=['GET'])
@login_required
def security_groups():
    groups = []
    
    try:
        # Conectar a la base de datos de security groups
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener todos los security groups (excepto el template con slice_id=0)
        cursor.execute("""
            SELECT id, slice_id, name, description, is_default, created_at, updated_at
            FROM security_groups 
            WHERE slice_id > 0
            ORDER BY slice_id, is_default DESC, name
        """)
        groups = cursor.fetchall()
        
        cursor.close()
        connection.close()
        
        print(f"DEBUG: {len(groups)} security groups encontrados", file=sys.stderr)
        
    except Error as e:
        print(f"DEBUG: Error al obtener security groups: {str(e)}", file=sys.stderr)
        flash(f'Error al cargar security groups: {str(e)}', 'error')
    
    return render_template('security_groups.html', groups=groups)

@app.route('/security-groups/create', methods=['GET', 'POST'])
@login_required
def create_security_group():
    if request.method == 'POST':
        nombre = request.form.get('name')
        descripcion = request.form.get('description')
        zona = request.form.get('zone', 'linux')
        
        # TODO: Llamada a API para crear security group
        # POST {DRIVERS_API}/security-groups-{zona}/create-custom
        
        flash(f"Security Group '{nombre}' creado exitosamente ✅", 'success')
        return redirect(url_for('security_groups'))
    
    return render_template('create_security_group.html')

@app.route('/security-group/<int:group_id>')
@login_required
def security_group_detail(group_id):
    """Obtener detalle de un security group y sus reglas desde la BD"""
    try:
        # Conectar a la base de datos de security groups
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener el security group con sus reglas
        cursor.execute("""
            SELECT id, slice_id, name, description, rules, is_default, created_at, updated_at
            FROM security_groups 
            WHERE id = %s
        """, (group_id,))
        sg_data = cursor.fetchone()
        
        cursor.close()
        connection.close()
        
        if not sg_data:
            flash('Security group no encontrado', 'error')
            return redirect(url_for('security_groups'))
        
        # Parsear las reglas JSON
        rules = []
        if sg_data['rules']:
            if isinstance(sg_data['rules'], str):
                rules = json.loads(sg_data['rules'])
            else:
                rules = sg_data['rules']
        
        print(f"DEBUG: Security group {group_id}: {sg_data['name']}, {len(rules)} reglas", file=sys.stderr)
        
        return render_template('security_group_detail.html', 
                             group_id=group_id,
                             group_name=sg_data['name'],
                             description=sg_data['description'],
                             slice_id=sg_data['slice_id'],
                             is_default=sg_data['is_default'],
                             rules=rules)
        
    except Error as e:
        print(f"DEBUG: Error al obtener security group: {str(e)}", file=sys.stderr)
        flash(f'Error al cargar security group: {str(e)}', 'error')
        return redirect(url_for('security_groups'))

@app.route('/security-group/<int:group_id>/delete-rule/<int:rule_id>', methods=['DELETE'])
@login_required
def delete_security_group_rule(group_id, rule_id):
    """Eliminar una regla de un security group"""
    try:
        data = request.get_json()
        id_openstack = data.get('id_openstack', '')
        
        # Conectar a BD para obtener info del security group
        connection = mysql.connector.connect(**SG_DB_CONFIG)
        cursor = connection.cursor(dictionary=True)
        
        # Obtener security group con sus reglas
        cursor.execute("""
            SELECT id, slice_id, name, rules, is_default
            FROM security_groups 
            WHERE id = %s
        """, (group_id,))
        sg_data = cursor.fetchone()
        
        if not sg_data:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Security group no encontrado'}), 404
        
        # Parsear reglas
        rules = []
        if sg_data['rules']:
            if isinstance(sg_data['rules'], str):
                rules = json.loads(sg_data['rules'])
            else:
                rules = sg_data['rules']
        
        # Validar que no es la última regla
        if len(rules) <= 1:
            cursor.close()
            connection.close()
            return jsonify({
                'success': False,
                'message': 'No se puede eliminar la única regla del security group. Debe mantener al menos una regla.'
            }), 400
        
        # Buscar la regla a eliminar
        rule_to_delete = None
        for rule in rules:
            if rule.get('id') == rule_id:
                rule_to_delete = rule
                break
        
        if not rule_to_delete:
            cursor.close()
            connection.close()
            return jsonify({'success': False, 'message': 'Regla no encontrada'}), 404
        
        cursor.close()
        connection.close()
        
        # Obtener zona de despliegue del slice desde la BD de slices
        slices_connection = mysql.connector.connect(**DB_CONFIG)
        slices_cursor = slices_connection.cursor(dictionary=True)
        slices_cursor.execute("SELECT zona_disponibilidad FROM slices WHERE id = %s", (sg_data['slice_id'],))
        slice_info = slices_cursor.fetchone()
        slices_cursor.close()
        slices_connection.close()
        
        if not slice_info:
            return jsonify({'success': False, 'message': 'Slice no encontrado'}), 404
        
        zona = slice_info['zona_disponibilidad']
        
        # Determinar endpoint según zona (basado en id_openstack)
        if id_openstack:
            # OpenStack: usar endpoint de OpenStack
            endpoint = f'{DRIVERS_API}/security-groups-openstack/remove-rule'
        else:
            # Linux: usar endpoint de Linux
            endpoint = f'{DRIVERS_API}/security-groups-linux/remove-rule'
        
        # Llamar al endpoint de drivers con el token de servicio
        response = requests.post(
            endpoint,
            json={
                'slice_id': sg_data['slice_id'],
                'zona_despliegue': zona,
                'sg_name': sg_data['name'],
                'rule_id': rule_id
            },
            headers={'Authorization': 'Bearer clavesihna'},
            timeout=30
        )
        
        if response.status_code == 200:
            return jsonify({'success': True, 'message': 'Regla eliminada exitosamente'})
        else:
            error_data = response.json() if response.headers.get('content-type') == 'application/json' else {'detail': response.text}
            return jsonify({
                'success': False,
                'message': error_data.get('detail', 'Error al eliminar regla')
            }), response.status_code
            
    except mysql.connector.Error as e:
        print(f"DEBUG: Error de BD: {str(e)}", file=sys.stderr)
        return jsonify({'success': False, 'message': f'Error de base de datos: {str(e)}'}), 500
    except requests.exceptions.RequestException as e:
        print(f"DEBUG: Error de conexión: {str(e)}", file=sys.stderr)
        return jsonify({'success': False, 'message': f'Error de conexión: {str(e)}'}), 503
    except Exception as e:
        print(f"DEBUG: Error general: {str(e)}", file=sys.stderr)
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500

@app.route('/security-group/<group_id>/add-rule', methods=['POST'])
@login_required
def add_security_group_rule(group_id):
    data = request.get_json()
    
    # TODO: Llamada a API para agregar regla
    # POST {DRIVERS_API}/security-groups-{zona}/add-rule
    
    return jsonify({'success': True, 'rule': data})

# --- NETWORKS ---
@app.route('/networks', methods=['GET'])
@login_required
def networks():
    networks_list = []
    
    # TODO: Llamada a API para obtener redes
    
    return render_template('networks.html', networks=networks_list)

@app.route('/networks/create', methods=['GET', 'POST'])
@login_required
def create_network():
    if request.method == 'POST':
        name = request.form.get('name')
        cidr = request.form.get('cidr')
        
        # TODO: Llamada a API para crear red
        
        flash(f"Red '{name}' creada exitosamente ✅", 'success')
        return redirect(url_for('networks'))
    
    return render_template('create_network.html')

# --- IMÁGENES ---
@app.route('/images')
@login_required
def images():
    return render_template('images.html')


@app.route('/api/images/list')
@login_required
def api_list_images():
    """Endpoint AJAX para obtener lista de imágenes"""
    try:
        # Llamar a slice_manager_api que hace proxy al image_manager
        headers = {
            'Authorization': f"Bearer {session.get('token')}"
        }
        
        response = requests.get(
            f'{SLICE_MANAGER_API}/img-mngr/list-images',
            headers=headers,
            timeout=10
        )
        
        # Verificar si el token expiró
        data, expired = handle_api_response(response)
        if expired:
            return jsonify({
                'success': False,
                'expired': True,
                'message': 'Sesión expirada'
            }), 401
        
        if response.status_code == 200:
            # Formatear respuesta
            images = data.get('images', [])
            return jsonify({
                'success': True,
                'total_images': len(images),
                'images': images
            })
        else:
            return jsonify({
                'success': False,
                'message': data.get('detail', 'Error al obtener imágenes')
            }), response.status_code
            
    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'message': 'No se pudo conectar con el servicio de imágenes'
        }), 503
    except requests.exceptions.Timeout:
        return jsonify({
            'success': False,
            'message': 'Tiempo de espera agotado'
        }), 504
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error interno: {str(e)}'
        }), 500


@app.route('/api/images/import-url', methods=['POST'])
@login_required
def api_import_image_url():
    """Endpoint para importar imagen desde URL"""
    try:
        data = request.get_json()
        
        if not data or 'url' not in data:
            return jsonify({
                'success': False,
                'message': 'URL requerida'
            }), 400
        
        # Preparar datos como form data (no JSON)
        form_data = {
            'nombre': data.get('nombre', 'imagen-importada'),
            'descripcion': data.get('descripcion', 'Imagen importada desde URL'),
            'url': data['url']
        }
        
        headers = {
            'Authorization': f"Bearer {session.get('token')}"
        }
        
        response = requests.post(
            f'{SLICE_MANAGER_API}/img-mngr/import-image',
            data=form_data,  # Enviar como form data, no json
            headers=headers,
            timeout=120  # Timeout largo porque descarga imagen
        )
        
        # Verificar si el token expiró
        data_response, expired = handle_api_response(response)
        if expired:
            return jsonify({
                'success': False,
                'expired': True,
                'message': 'Sesión expirada'
            }), 401
        
        if response.status_code == 200:
            return jsonify({
                'success': True,
                'message': 'Imagen importada exitosamente',
                'data': data_response
            })
        else:
            return jsonify({
                'success': False,
                'message': data_response.get('detail', 'Error al importar imagen')
            }), response.status_code
            
    except requests.exceptions.Timeout:
        return jsonify({
            'success': False,
            'message': 'Tiempo de espera agotado. La imagen puede ser muy grande.'
        }), 504
    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'message': 'No se pudo conectar con el servicio'
        }), 503
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error interno: {str(e)}'
        }), 500


@app.route('/api/images/upload-file', methods=['POST'])
@login_required
def api_upload_image_file():
    """Endpoint para subir imagen desde archivo"""
    try:
        if 'file' not in request.files:
            return jsonify({
                'success': False,
                'message': 'No se proporcionó archivo'
            }), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({
                'success': False,
                'message': 'Archivo vacío'
            }), 400
        
        # Preparar form data
        form_data = {
            'nombre': request.form.get('nombre', file.filename.split('.')[0]),
            'descripcion': request.form.get('descripcion', 'Imagen subida desde archivo')
        }
        
        files = {
            'file': (file.filename, file.stream, file.content_type)
        }
        
        headers = {
            'Authorization': f"Bearer {session.get('token')}"
        }
        
        response = requests.post(
            f'{SLICE_MANAGER_API}/img-mngr/upload-image',
            data=form_data,
            files=files,
            headers=headers,
            timeout=180  # Timeout muy largo para archivos grandes
        )
        
        # Verificar si el token expiró
        data_response, expired = handle_api_response(response)
        if expired:
            return jsonify({
                'success': False,
                'expired': True,
                'message': 'Sesión expirada'
            }), 401
        
        if response.status_code == 200:
            return jsonify({
                'success': True,
                'message': 'Imagen subida exitosamente',
                'data': data_response
            })
        else:
            return jsonify({
                'success': False,
                'message': data_response.get('detail', 'Error al subir imagen')
            }), response.status_code
            
    except requests.exceptions.Timeout:
        return jsonify({
            'success': False,
            'message': 'Tiempo de espera agotado. El archivo puede ser muy grande.'
        }), 504
    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'message': 'No se pudo conectar con el servicio'
        }), 503
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error interno: {str(e)}'
        }), 500


@app.route('/api/images/delete/<int:image_id>', methods=['DELETE'])
@login_required
def api_delete_image(image_id):
    """Endpoint para eliminar imagen"""
    try:
        headers = {
            'Authorization': f"Bearer {session.get('token')}"
        }
        
        response = requests.delete(
            f'{SLICE_MANAGER_API}/img-mngr/delete-image/{image_id}',
            headers=headers,
            timeout=60
        )
        
        # Verificar si el token expiró
        data_response, expired = handle_api_response(response)
        if expired:
            return jsonify({
                'success': False,
                'expired': True,
                'message': 'Sesión expirada'
            }), 401
        
        if response.status_code == 200:
            return jsonify({
                'success': True,
                'message': 'Imagen eliminada exitosamente'
            })
        else:
            return jsonify({
                'success': False,
                'message': data_response.get('detail', 'Error al eliminar imagen')
            }), response.status_code
            
    except requests.exceptions.Timeout:
        return jsonify({
            'success': False,
            'message': 'Tiempo de espera agotado'
        }), 504
    except requests.exceptions.ConnectionError:
        return jsonify({
            'success': False,
            'message': 'No se pudo conectar con el servicio'
        }), 503
    except Exception as e:
        return jsonify({
            'success': False,
            'message': f'Error interno: {str(e)}'
        }), 500


if __name__ == '__main__':
    import logging
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host='0.0.0.0', port=5000, debug=False)
