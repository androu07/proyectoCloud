#!/usr/bin/env python3
"""
Script para verificar la conectividad con la API remota
Ejecutar antes de usar la aplicación para asegurarse que el túnel SSH está activo
"""

import requests
import urllib3
import sys

# Deshabilitar warnings de SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def test_connection():
    """Probar la conexión con la API"""
    api_url = "https://localhost:8443"
    
    print("="*70)
    print("🔍 VERIFICADOR DE CONECTIVIDAD API")
    print("="*70)
    print(f"\n📍 URL de la API: {api_url}")
    print(f"⏱️  Timeout configurado: 10 segundos")
    print("\n" + "-"*70)
    
    # Test 1: Conexión básica al servidor
    print("\n1️⃣  Probando conexión básica al servidor...")
    try:
        response = requests.get(
            f"{api_url}/",
            verify=False,
            timeout=10
        )
        print(f"   ✅ Conexión exitosa (Status: {response.status_code})")
    except requests.exceptions.Timeout:
        print("   ❌ ERROR: Timeout - El servidor no responde en 10 segundos")
        print("   💡 Solución: Verifique que el túnel SSH está activo:")
        print("      ssh -NL 8443:localhost:443 ubuntu@10.20.12.97 -p 5801")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ ERROR: No se pudo conectar al servidor")
        print(f"   💡 Detalles: {str(e)}")
        print("   💡 Solución: Verifique que el túnel SSH está activo:")
        print("      ssh -NL 8443:localhost:443 ubuntu@10.20.12.97 -p 5801")
        return False
    except Exception as e:
        print(f"   ❌ ERROR: {type(e).__name__}: {str(e)}")
        return False
    
    # Test 2: Endpoint de health check (si existe)
    print("\n2️⃣  Probando endpoints de la API...")
    endpoints_to_test = [
        "/auth/login",
        "/slices/listar_slices",
    ]
    
    for endpoint in endpoints_to_test:
        try:
            response = requests.get(
                f"{api_url}{endpoint}",
                verify=False,
                timeout=10
            )
            print(f"   ✅ {endpoint} - Status: {response.status_code}")
        except requests.exceptions.Timeout:
            print(f"   ⚠️  {endpoint} - Timeout (puede requerir autenticación)")
        except Exception as e:
            print(f"   ⚠️  {endpoint} - {type(e).__name__}")
    
    print("\n" + "="*70)
    print("✅ VERIFICACIÓN COMPLETADA")
    print("="*70)
    print("\n💡 Recordatorios:")
    print("   • El túnel SSH debe estar activo ANTES de usar la aplicación")
    print("   • Comando SSH: ssh -NL 8443:localhost:443 ubuntu@10.20.12.97 -p 5801")
    print("   • Los timeouts ahora son más largos:")
    print("     - Creación de slices: 60 segundos")
    print("     - Otras operaciones: 30 segundos")
    print("     - Listado: 20 segundos")
    print("\n")
    return True

if __name__ == "__main__":
    success = test_connection()
    sys.exit(0 if success else 1)
