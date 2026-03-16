# Toma de nota

## ¿Qué se busca?

Determinar a qué cliente se le debería asignar cada prestador

- Existen +800 firmas prestadoras (similares a NITs)
- Cada prestador cuenta con asesores (personas)
- El proceso de contratación, habilitación y asignación de órdenes de compra se ha centralizado. Desde entonces se ha generado un cuello de botella
- Se requiere identificar el prestador más idóneo para atender a cada cliente
- Un asesor puede tener múltiples programas o tareas asociadas

---

## Actores

- **Cliente:** A quien se necesita atender
- **Prestador:** Capacidad extendida de la ARL; quien presta el servicio

---

## Base de datos prestadores (clientes?)

- Los tipos de perfil están definidos por la experticia del prestador
- Se consideran las capacidades del asesor
- La tarifa del prestador depende del nivel de especialización
- A perfiles más especializados se les asignan problemas de mayor complejidad

---

## Base de datos de órdenes de compra

- Base de datos de órdenes de compra y su consumo
- La orden funciona como llave única

---

## Archivos

1. Tareas prestador bloque (prestadores). Corresponde a la base de datos de prestadores (clientes?)
2. Tareas programadas/canceladas con estados
3. Datos básicos cliente. Archivo aninimizado; detalles de empresas
4. Órdenes de compra consolidadas (ordenadas). Corresponde a la base de datos de órdenes de compra y su consumo

Con la información proporcionada se debe hacer una aproximación al clúster
