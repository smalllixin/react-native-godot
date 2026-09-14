/**************************************************************************/
/*  GodotModule.cpp                                                       */
/**************************************************************************/
/* Copyright (c) 2024-2025 Slay GmbH                                      */
/*                                                                        */
/* Permission is hereby granted, free of charge, to any person obtaining  */
/* a copy of this software and associated documentation files (the        */
/* "Software"), to deal in the Software without restriction, including    */
/* without limitation the rights to use, copy, modify, merge, publish,    */
/* distribute, sublicense, and/or sell copies of the Software, and to     */
/* permit persons to whom the Software is furnished to do so, subject to  */
/* the following conditions:                                              */
/*                                                                        */
/* The above copyright notice and this permission notice shall be         */
/* included in all copies or substantial portions of the Software.        */
/*                                                                        */
/* THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,        */
/* EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF     */
/* MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. */
/* IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY   */
/* CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,   */
/* TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE      */
/* SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.                 */
/**************************************************************************/

#include "GodotModule.h"
#define LOG_TAG "GodotModule"
#include "godot-log.h"

#include "libgodot_android.h"
#include "libgodot_jni.h"
#include <godot_cpp/classes/display_server_embedded.hpp>
#include <godot_cpp/classes/gd_extension_manager.hpp>
#include <godot_cpp/classes/rendering_native_surface.hpp>
#include <godot_cpp/classes/rendering_native_surface_android.hpp>
#include <godot_cpp/godot.hpp>

#include <android/choreographer.h>
#include <android/looper.h>
#include <android/native_window.h>
#include <android/native_window_jni.h>
#include <dlfcn.h>

#include <unistd.h>
#include <map>
#include <queue>
#include <string>

typedef GDExtensionObjectPtr (*libgodot_create_godot_instance_android_type)(int p_argc, char *p_argv[], GDExtensionInitializationFunction p_init_func, JNIEnv *env, jobject p_asset_manager, jobject p_net_utils, jobject p_directory_access_handler, jobject p_file_access_handler, jobject p_godot_io_wrapper, jobject p_godot_wrapper, jobject p_class_loader);
typedef void (*libgodot_destroy_godot_instance_type)(GDExtensionObjectPtr p_godot_instance);

const static char CMD_FUNCTION = 1;
const static char CMD_EXIT = 2;

class AndroidThread {
	std::thread thread;
	std::mutex mutex;
	std::condition_variable started;
	std::queue<std::function<void()>> tasks;
	ALooper *looper = nullptr;
	int function_queue_fd = -1;
	bool quit = false;

public:
    std::function<bool()> tick;
    bool isCurrent() const { return thread.get_id() == std::this_thread::get_id(); }
	AndroidThread() :
			thread(&AndroidThread::run, this) {
		std::unique_lock<std::mutex> lock(mutex);
		started.wait(lock, [this]() {
			return function_queue_fd >= 0;
		});
	}

	static int looper_callback(int fd, int events, void *data) {
		char cmd;
		AndroidThread *self = (AndroidThread *)data;
		ssize_t res = read(fd, &cmd, sizeof(cmd));
		if (res < 0) {
			LOGE("Unable to read looper event from pipe: %d", errno);
			return 1;
		}
		if (res == 0) {
			LOGE("End of file event should not happen.");
			return 1;
		}
		if (res != sizeof(cmd)) {
			LOGE("Unable to read command fully from pipe");
			return 1;
		}

		switch (cmd) {
			case CMD_FUNCTION: {
				std::function<void()> task;
				{
					std::lock_guard<std::mutex> lock(self->mutex);
					if (self->tasks.empty()) {
						LOGW("Empty queue when processing CMD_FUNCTION");
						break;
					}
					task = std::move(self->tasks.front());
					self->tasks.pop();
				}
				task();
			} break;
			case CMD_EXIT: {
				self->quit = true;
			} break;
			default: {
				LOGE("Unknown command: %d", cmd);
			}
		}

		return 1;
	}

	void enqueue(std::function<void()> f) {
		if (thread.get_id() == std::this_thread::get_id()) {
			f();
			return;
		}
		{
			std::lock_guard<std::mutex> lock(mutex);
			tasks.emplace(f);
		}
		ssize_t res = write(function_queue_fd, &CMD_FUNCTION, sizeof(CMD_FUNCTION));
		if (res < 0) {
			LOGE("Unable to write to pipe: %d", errno);
		}
		if (res != sizeof(CMD_FUNCTION)) {
			LOGE("Unable to write command fully to pipe");
		}
	}

	void run() {
		LOGI("AndroidThread Looper thread started.");
		LibGodot::get_jni_env(); // Force attaching to Java VM
		{
			std::lock_guard<std::mutex> lock(mutex);

			// Prepare Looper
			looper = ALooper_prepare(0);

			// Register callback for function
			int fds[2];
			int res = pipe(fds);
			if (res < 0) {
				LOGE("Unable to create pipe for ALooper: %d", errno);
				return; // TODO: Abort app
			}
			ALooper_addFd(looper, fds[0], ALOOPER_POLL_CALLBACK, ALOOPER_EVENT_INPUT, AndroidThread::looper_callback, this);
			function_queue_fd = fds[1];
			started.notify_all();
		}

        bool rendered = false;
        while (!quit) {
            int outFd;
            int outEvents;
            void *outData;
            // Godot owns active frame pacing. Block only when paused/stopped;
            // queued commands wake the looper even when no frame is rendered.
            int result = ALooper_pollOnce(rendered ? 0 : -1, &outFd, &outEvents, &outData);
            // Drain a bounded batch so touch traffic cannot accumulate one task
            // per frame, while still giving rendering a chance under heavy input.
            for (int pending = 0; result == ALOOPER_POLL_CALLBACK && pending < 63 && !quit; ++pending) {
                result = ALooper_pollOnce(0, &outFd, &outEvents, &outData);
            }
            if (result == ALOOPER_POLL_ERROR) LOGE("ALooper_pollOnce internal error.");
            rendered = !quit && tick && tick();
        }

		ALooper_release(looper);
		LOGI("AndroidThread Looper thread exited.");
	}
};

typedef struct FuncData {
	std::function<void()> func;
	jobject ref;
	FuncData() :
			func(nullptr), ref(nullptr) {}
	FuncData(std::function<void()> p_func, jobject p_ref) :
			func(p_func), ref(p_ref) {}
} FuncData;

typedef struct WindowFuncData {
	std::function<void(bool)> func;
	jobject ref;
	WindowFuncData() :
			func(nullptr), ref(nullptr) {}
	WindowFuncData(std::function<void(bool)> p_func, jobject p_ref) :
			func(p_func), ref(p_ref) {}
} WindowFuncData;

struct AndroidPlatformData : PlatformData {
	ANativeWindow *mainNativeWindow = nullptr;
	godot::Ref<godot::RenderingNativeSurface> mainSurface;

	void *handle = nullptr;
	libgodot_create_godot_instance_android_type func_libgodot_create_godot_instance_android = nullptr;
	libgodot_destroy_godot_instance_type func_libgodot_destroy_godot_instance = nullptr;
	double contentScaleFactor = 1.0;
	std::map<std::string, WindowFuncData> windowUpdateCallbacks;
	std::map<void *, std::string> handleToWindowName;
	bool in_background = false;
	bool paused = false;
	AndroidThread thread;
	std::mutex windowUpdateMutex;
	std::mutex createMutex;
};

GodotModule *GodotModule::get_singleton() {
	static GodotModule *singleton = new GodotModule(new AndroidPlatformData());
	return singleton;
}

extern "C" {

static void initialize_default_module(godot::ModuleInitializationLevel p_level) {
	if (p_level != godot::MODULE_INITIALIZATION_LEVEL_SCENE) {
		return;
	}
}

static void uninitialize_default_module(godot::ModuleInitializationLevel p_level) {
	if (p_level != godot::MODULE_INITIALIZATION_LEVEL_SCENE) {
		return;
	}
}

GDExtensionBool GDE_EXPORT gdextension_default_init(GDExtensionInterfaceGetProcAddress p_get_proc_address, GDExtensionClassLibraryPtr p_library, GDExtensionInitialization *r_initialization) {
	godot::GDExtensionBinding::InitObject init_object(p_get_proc_address, p_library, r_initialization);

	init_object.register_initializer(initialize_default_module);
	init_object.register_terminator(uninitialize_default_module);
	init_object.set_minimum_library_initialization_level(godot::MODULE_INITIALIZATION_LEVEL_SCENE);

	return init_object.init();
}
}

godot::GodotInstance *GodotModule::get_or_create_instance(std::vector<std::string> args) {
	AndroidPlatformData *data = static_cast<AndroidPlatformData *>(_data);

	// Make sure that we only run this method once at a time.
	std::lock_guard createLock(data->createMutex);

	{
		std::lock_guard lock(_mutex);
		if (_instance) {
			return _instance;
		}
	}

	_generation.fetch_add(1); _sessionState = 1;
	void *handle = data->handle;
	if (!data->func_libgodot_create_godot_instance_android) {
		libgodot_create_godot_instance_android_type func_libgodot_create_godot_instance_android = nullptr;
#ifndef LIBGODOT_STATIC
		handle = dlopen("libgodot_android.so", RTLD_LAZY | RTLD_LOCAL);

		if (handle == nullptr) {
			LOGI("Unable to open libgodot_android.so: %s", dlerror());
            _sessionState = 5;
			return nullptr;
		}
		func_libgodot_create_godot_instance_android = (libgodot_create_godot_instance_android_type)dlsym(handle, "libgodot_create_godot_instance_android");

		if (func_libgodot_create_godot_instance_android == nullptr) {
			LOGE("Unable to load libgodot_create_godot_instance symbol: %s", dlerror());
			dlclose(handle);
			handle = nullptr;
            _sessionState = 5;
			return nullptr;
		}
#else
		func_libgodot_create_godot_instance_android = libgodot_create_godot_instance_android;
#endif
		{
			std::lock_guard lock(_mutex);
			data->func_libgodot_create_godot_instance_android = func_libgodot_create_godot_instance_android;
            data->handle = handle;
		}
	}

	std::vector<std::string> cmdline{ "apk" };
	for (std::string arg : args) {
		cmdline.push_back(arg);
	}

	std::vector<const char *> cargs{};
	for (const std::string &arg : cmdline) {
		cargs.push_back(arg.c_str());
	}

	GDExtensionObjectPtr instance_ptr = nullptr;
	{
		std::lock_guard lock(_mutex);
		instance_ptr = data->func_libgodot_create_godot_instance_android(
				cargs.size(),
				(char **)cargs.data(),
				gdextension_default_init,
				LibGodot::get_jni_env(),
				LibGodot::get_asset_manager(),
				LibGodot::get_net_utils(),
				LibGodot::get_dir_access_handler(),
				LibGodot::get_file_access_handler(),
				LibGodot::get_godot_io(),
				LibGodot::get_godot_engine(),
				LibGodot::get_class_loader());
	}

	if (instance_ptr == nullptr) {
        _sessionState = 5;
		// Unable to start Godot
		LOGI("Unable to start Godot");
		return nullptr;
	}

	godot::GodotInstance *instance = reinterpret_cast<godot::GodotInstance *>(godot::internal::get_object_instance_binding(instance_ptr));

	// Initialize Android Surface
	ANativeWindow *mainNativeWindow = LibGodot::get_main_surface();
	uint32_t width = LibGodot::get_main_width();
	uint32_t height = LibGodot::get_main_height();

	// TODO: Set main window surface size and position
	// TODO: Get content scale factor from Android
	// data->contentScaleFactor = [[UIScreen mainScreen] scale];
	double contentScaleFactor = 1.0;
	// TODO: Set content scale factor in the surface

	godot::Ref<godot::RenderingNativeSurfaceAndroid> androidSurface = godot::RenderingNativeSurfaceAndroid::create((uint64_t)mainNativeWindow, width, height);

	godot::RenderingNativeSurface *ptr = godot::Object::cast_to<godot::RenderingNativeSurface>(androidSurface.ptr());
	godot::Ref<godot::RenderingNativeSurface> nativeSurface(ptr);

	godot::DisplayServerEmbedded::set_native_surface(nativeSurface);

    if (!instance->start()) {
        auto destroy = reinterpret_cast<libgodot_destroy_godot_instance_type>(dlsym(handle, "libgodot_destroy_godot_instance"));
        godot::DisplayServerEmbedded::set_native_surface({}); nativeSurface.unref(); androidSurface.unref();
        if (destroy) destroy(instance_ptr);
        #if GODOT_VERSION_MINOR < 7
        godot::GDExtensionBinding::deinit();
#else
        godot::GDExtensionBinding::api_initialized = false;
#endif
        _sessionState = 5; return nullptr;
    }

	{
		std::lock_guard lock(_mutex);

		data->mainNativeWindow = mainNativeWindow;
		data->mainSurface = nativeSurface;
		data->contentScaleFactor = contentScaleFactor;
		data->handle = handle;

		_instance = instance;
	}

	_sessionState = data->paused || data->in_background ? 3 : 2;
    data->thread.tick = [this]() { if (is_paused()) return false; iterate(); return true; };
	updateWindows(true);

	return instance;
}

double GodotModule::get_content_scale_factor() {
	std::lock_guard lock(_mutex);
	if (!_instance) {
		return 1.0;
	}

	AndroidPlatformData *data = static_cast<AndroidPlatformData *>(_data);

	return data->contentScaleFactor;
}

void GodotModule::destroy_instance() {
	AndroidPlatformData *data = static_cast<AndroidPlatformData *>(_data);

	// Make sure that we only run this method once at a time.
	std::lock_guard createLock(data->createMutex);

	if (!_instance) {
		LOGI("Godot instance is already destroyed.");
		return;
	}

	_sessionState = 4; _generation.fetch_add(1); data->thread.tick = nullptr;
	if (!data->func_libgodot_destroy_godot_instance) {
		libgodot_destroy_godot_instance_type func_libgodot_destroy_godot_instance = nullptr;
#ifndef LIBGODOT_STATIC
		void *handle = nullptr;

		{
			std::lock_guard lock(_mutex);
			handle = data->handle;
		}

		if (handle == nullptr) {
			LOGI("Unable to open libgodot_android.so: %s", dlerror());
			return;
		}
		func_libgodot_destroy_godot_instance = (libgodot_destroy_godot_instance_type)dlsym(handle, "libgodot_destroy_godot_instance");

		if (func_libgodot_destroy_godot_instance == nullptr) {
			LOGE("Unable to load libgodot_destroy_godot_instance symbol: %s", dlerror());
			dlclose(handle);
			handle = nullptr;
			return;
		}
#else
		func_libgodot_destroy_godot_instance = libgodot_destroy_godot_instance;
#endif
		{
			std::lock_guard lock(_mutex);
			data->func_libgodot_destroy_godot_instance = func_libgodot_destroy_godot_instance;
		}
	}

	{
		std::lock_guard lock(_mutex);

		godot::DisplayServerEmbedded::set_native_surface(godot::Ref<godot::RenderingNativeSurface>(nullptr));
		// The JNI surface map owns the native-window reference.
		data->mainNativeWindow = nullptr;
		data->mainSurface = godot::Ref<godot::RenderingNativeSurface>(nullptr);

		data->func_libgodot_destroy_godot_instance(_instance->_owner);
		_instance = nullptr;
		#if GODOT_VERSION_MINOR < 7
        godot::GDExtensionBinding::deinit();
#else
        godot::GDExtensionBinding::api_initialized = false;
#endif

		// Keep the engine library loaded; Java services also reference its JNI symbols.

		_sessionState = 0;
	}
}

godot::Ref<godot::RenderingNativeSurface> GodotModule::get_main_rendering_surface() {
	std::lock_guard lock(_mutex);
	AndroidPlatformData *data = static_cast<AndroidPlatformData *>(_data);
	return data->mainSurface;
}
void GodotModule::focus_out() { appPause(); }
void GodotModule::focus_in() { appResume(); }
bool GodotModule::is_paused() {
    std::lock_guard lock(_mutex);
    auto *data = static_cast<AndroidPlatformData *>(_data);
    return data->paused || data->in_background;
}
void GodotModule::appPause() {
    runOnGodotThread([this]() {
        auto *data = static_cast<AndroidPlatformData *>(_data);
        { std::lock_guard lock(_mutex); data->in_background = true; }
        if (_instance) { _instance->focus_out(); _sessionState = 3; }
    });
}
void GodotModule::appResume() {
    runOnGodotThread([this]() {
        auto *data = static_cast<AndroidPlatformData *>(_data);
        { std::lock_guard lock(_mutex); data->in_background = false; }
        if (_instance) { _instance->focus_in(); updateState(); }
    });
}
void GodotModule::pause() {
    runOnGodotThread([this]() {
        auto *data = static_cast<AndroidPlatformData *>(_data);
        { std::lock_guard lock(_mutex); data->paused = true; }
        updateState();
    });
}
void GodotModule::resume() {
    runOnGodotThread([this]() {
        auto *data = static_cast<AndroidPlatformData *>(_data);
        { std::lock_guard lock(_mutex); data->paused = false; }
        updateState();
    });
}
void GodotModule::updateState() { if (_instance) _sessionState = is_paused() ? 3 : 2; }

class CPPCallable : public godot::CallableCustom {
	//    friend bool javascript_callable_compare_equal_func(const godot::CallableCustom *p_a, const godot::CallableCustom *p_b) {
	//        if (p_a == p_b) return true;
	//        const JavascriptCallable *a = static_cast<const JavascriptCallable *>(p_a);
	//        const JavascriptCallable *b = static_cast<const JavascriptCallable *>(p_b);
	//        return jsi::Function::strictEquals(a->_rt, a->_func, b->_func);
	//    };

	std::function<void(const godot::Variant **, int, godot::Variant &, GDExtensionCallError &)> _func;

public:
	CPPCallable(std::function<void(const godot::Variant **, int, godot::Variant &, GDExtensionCallError &)> f) :
			_func(f) {}

	uint32_t hash() const override {
		return 0; // Use default hash function
	}
	godot::String get_as_text() const override {
		return godot::String("CPPCallable");
	}
	CompareEqualFunc get_compare_equal_func() const override {
		return nullptr;
	}

	CompareLessFunc get_compare_less_func() const override {
		return nullptr;
	}

	bool is_valid() const override {
		return true;
	}
	godot::ObjectID get_object() const override {
		return godot::ObjectID();
	}
	void call(const godot::Variant **p_arguments, int p_argcount, godot::Variant &r_return_value, GDExtensionCallError &r_call_error) const override {
		_func(p_arguments, p_argcount, r_return_value, r_call_error);
		r_call_error.error = GDEXTENSION_CALL_OK;
	}
};

godot::Callable GodotModule::create_callable(std::function<void(const godot::Variant **, int, godot::Variant &, GDExtensionCallError &)> f) {
	return godot::Callable(memnew(CPPCallable(f)));
}

void GodotModule::registerWindowUpdateCallback(std::string name, void *handle, std::function<void(bool)> f, void *ref) {
	AndroidPlatformData *data = static_cast<AndroidPlatformData *>(_data);
	std::lock_guard lock(data->windowUpdateMutex);
	LOGD("Registering Window: %p, %s", handle, name.c_str());
	if (data->handleToWindowName.contains(handle)) {
		std::string currentName = data->handleToWindowName[handle];
		if (currentName != name) {
			LOGE("RegisterWindowUpdateCallback: Unable to register a different name for the same handle");
			return;
		}
	} else {
		data->handleToWindowName[handle] = name;
	}
	data->windowUpdateCallbacks[name] = WindowFuncData(f, (jobject)ref);
}

void GodotModule::unregisterWindowUpdateCallback(void *handle) {
	AndroidPlatformData *data = static_cast<AndroidPlatformData *>(_data);
	std::lock_guard lock(data->windowUpdateMutex);
	if (data->handleToWindowName.contains(handle)) {
		std::string name = data->handleToWindowName[handle];
		LOGD("Unregistering Window: %p, %s", handle, name.c_str());
		WindowFuncData fd = data->windowUpdateCallbacks[name];
		JNIEnv *env = LibGodot::get_jni_env();
		env->DeleteGlobalRef(fd.ref);
		data->windowUpdateCallbacks.erase(name);
		data->handleToWindowName.erase(handle);
	}
}

void GodotModule::updateWindow(std::string name, bool adding) {
	LibGodot::updateWindow(name);
	AndroidPlatformData *data = static_cast<AndroidPlatformData *>(_data);
	std::function<void(bool)> cb;
	{
		std::lock_guard lock(data->windowUpdateMutex);
		if (!data->windowUpdateCallbacks.contains(name)) {
			return;
		}
		cb = data->windowUpdateCallbacks[name].func;
	}
	cb(true);
}

void GodotModule::updateWindows(bool adding) {
	LibGodot::updateWindows();
	AndroidPlatformData *data = static_cast<AndroidPlatformData *>(_data);
	std::map<std::string, WindowFuncData> callbacks;
	{
		std::lock_guard lock(data->windowUpdateMutex);
		callbacks = data->windowUpdateCallbacks;
	}
	for (const std::pair<std::string, WindowFuncData> elem : callbacks) {
		LOGD("Updating Window: %s", elem.first.c_str());
		elem.second.func(true);
	}
}

void GodotModule::runOnGodotThread(std::function<void()> f, bool wait) {
    auto *data = static_cast<AndroidPlatformData *>(_data);
    if (data->thread.isCurrent()) { f(); return; }
    if (!wait) { data->thread.enqueue(std::move(f)); return; }
    auto completed = std::make_shared<std::promise<void>>();
    auto future = completed->get_future();
    data->thread.enqueue([f = std::move(f), completed]() {
        try { f(); completed->set_value(); }
        catch (...) { completed->set_exception(std::current_exception()); }
    });
    future.get();
}

void GodotModule::iterate() {
	godot::GodotInstance *instance = nullptr;
	{
		std::lock_guard lock(_mutex);
		instance = _instance;
	}
	if (instance && instance->is_started()) {
		instance->iteration();
	}
}
