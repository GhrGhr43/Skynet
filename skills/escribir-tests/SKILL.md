---
name: escribir-tests
description: Añadir o arreglar tests automáticos de un repo (pytest, unittest, jest) sin cambiar el comportamiento del código. Úsala cuando la tarea pida tests, cobertura o reproducir un fallo con un test.
---

# Escribir tests

1. Antes de escribir nada, mira cómo están hechos los tests que ya hay (carpeta, nombres,
   fixtures, framework) y copia ese estilo. No añadas un framework nuevo.
2. Si la tarea es un fallo: escribe primero el test que lo reproduce y comprueba que falla.
   Solo entonces arregla el código, y el mismo test debe pasar.
3. Un test por comportamiento, con un nombre que diga qué se comprueba
   (`test_resta_con_negativos`, no `test_2`).
4. Casos a cubrir: el normal, los bordes (vacío, cero, uno, máximo) y la entrada inválida.
5. Sin red, sin reloj real, sin rutas absolutas de la máquina: usa carpetas temporales
   (`tmp_path` en pytest) y datos inventados.
6. No borres ni debilites tests que ya existen para que pase el verificador. Si uno está
   mal, dilo en la respuesta en vez de tocarlo.
7. Al terminar, ejecuta el verificador del repo y cuenta en la respuesta cuántos tests hay,
   cuántos pasan y qué queda pendiente.
