# Política de seguridad — Bordagran Facturas

Este repositorio es público, pero procesa información fiscal y se integra con servicios privados de Google. El código público nunca debe contener credenciales, tokens, facturas ni datos personales de clientes o proveedores.

## Comunicación responsable
No publiques vulnerabilidades explotables, secretos, facturas ni datos personales en incidencias públicas. Comunica el problema de forma privada al responsable del repositorio o mediante el canal privado de avisos de seguridad de GitHub, si está habilitado.

## Reglas de mantenimiento
- No subir `credentials.json`, `token.pickle`, `token.json`, archivos `.env`, claves privadas, PDFs de facturas o volcados de Gmail/Drive/Sheets.
- Mantener los permisos OAuth limitados a lo imprescindible.
- Revisar Dependabot y las alertas de dependencias antes de integrar cambios.
- Comprobar que la publicación de configuraciones, identificadores de recursos, correos y rutas no exponga información operativa innecesaria.
- Revisar el historial del repositorio en busca de secretos: añadir archivos a `.gitignore` no elimina datos previamente publicados.
- Si un secreto se publica, revocarlo o rotarlo en su proveedor; eliminar el archivo del último commit no basta.

## Comprobaciones recomendadas
Antes de cada cambio significativo, validar el programa, sus dependencias y la ausencia de secretos. Mantener habilitadas las alertas de seguridad de GitHub cuando estén disponibles.
