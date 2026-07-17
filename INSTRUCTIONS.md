# Reglas del proyecto

Despues de cada interaccion del usuario, documenta los cambios realizados
en el archivo `Cambios_Realizados.md` en la raiz del proyecto.

## Formato de registro

Cada entrada debe tener:

- **Fecha y hora** (ej: `2026-07-15 14:30`)
- **Descripcion breve** de lo que se hizo o modifico
- **Archivos involucrados** (creados, modificados, eliminados)

Ejemplo:

```
## 2026-07-15 14:30
- **Que se hizo:** Se agrego el modelo User con relacion 1:N a Item.
- **Archivos:** app/models/user.py (nuevo), app/models/item.py (modificado), app/api/endpoints.py (modificado)
```
