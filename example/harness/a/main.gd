extends Node3D
signal host_event(payload: String)
var cube: MeshInstance3D
var taps := 0
var frames := 0
func _ready():
 Engine.max_fps = 30
 cube = MeshInstance3D.new()
 cube.mesh = BoxMesh.new()
 var material = StandardMaterial3D.new()
 material.albedo_color = Color(0.2, 0.45, 0.9)
 cube.material_override = material
 add_child(cube)
 var camera = Camera3D.new()
 camera.position = Vector3(0, 2, 5)
 add_child(camera)
 camera.look_at(Vector3.ZERO)
 var light = DirectionalLight3D.new()
 light.rotation_degrees = Vector3(-45, -30, 0)
 add_child(light)
func _process(delta):
 frames += 1
 cube.rotate_y(delta * 0.5)
func _unhandled_input(event):
 if event is InputEventScreenTouch and event.pressed:
  taps += 1
  host_event.emit(JSON.stringify({"type":"tap", "count":taps, "text":"你好，G 🐈"}))
func status_json():
 return JSON.stringify({"variant":"a", "taps":taps, "frames":frames})

func echo_event(text: String):
 host_event.emit(JSON.stringify({"type":"echo", "text":text}))
