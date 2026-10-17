/**************************************************************************/
/*  RTNGodotView.mm                                                       */
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

#import <React/RCTLog.h>
#import <React/RCTUIManager.h>

#include <libgodot/libgodot.h>
#include <godot_cpp/classes/display_server_embedded.hpp>
#include <godot_cpp/classes/engine.hpp>
#include <godot_cpp/classes/godot_instance.hpp>
#include <godot_cpp/classes/main_loop.hpp>
#include <godot_cpp/classes/rendering_native_surface.hpp>
#include <godot_cpp/classes/rendering_native_surface_apple.hpp>
#include <godot_cpp/classes/scene_tree.hpp>
#include <godot_cpp/classes/window.hpp>
#include <godot_cpp/core/math.hpp>
#include <godot_cpp/godot.hpp>
#include <godot_cpp/variant/utility_functions.hpp>

#include "GodotModule.h"

#import "RTNGodotView.h"

#import <react/renderer/components/RTNGodotSpec/ComponentDescriptors.h>
#import <react/renderer/components/RTNGodotSpec/EventEmitters.h>
#import <react/renderer/components/RTNGodotSpec/Props.h>
#import <react/renderer/components/RTNGodotSpec/RCTComponentViewHelpers.h>

using namespace facebook::react;

static const int MAX_TOUCH_COUNT = 32;

static NSMutableArray<UIView *> *_views = [NSMutableArray array];
static UIView *_currentView = nil;

@interface RTNGodotView () <RCTRTNGodotViewViewProtocol>
@end
@implementation RTNGodotView {
	NSString *_windowName;
	CALayer *_renderingLayer;
	uint64_t _windowId;
	godot::Ref<godot::RenderingNativeSurface> _nativeSurface;
	std::vector<UITouch *> _touches;
	bool _propsUpdated;
	bool _instanceCallbackRegistered;
	bool _addingGodotView;
    uint64_t _attachmentGeneration;
    uint64_t _attachmentRequest;
}

+ (BOOL)shouldBeRecycled {
	return NO;
}

+ (void)removeMainLayerFromGodotView:(UIView *)view {
	if (![_views containsObject:view]) {
		return;
	}

	CALayer *mainLayer = (__bridge CALayer *)GodotModule::get_singleton()->get_main_rendering_layer();

	if (view == _currentView) {
		if (mainLayer) {
			[mainLayer removeFromSuperlayer];
		}
	}
	[_views removeObject:view];

	if (_views.count > 0) {
		_currentView = [_views lastObject];
		if (mainLayer) {
			[_currentView.layer addSublayer:mainLayer];
			[_currentView setNeedsLayout];
		}
	} else {
		_currentView = nil;
	}
}

+ (CALayer *)addMainLayerToGodotView:(UIView *)view {
	CALayer *mainLayer = (__bridge CALayer *)GodotModule::get_singleton()->get_main_rendering_layer();
    if (!mainLayer) return nil;
	if (![_views containsObject:view]) {
		[_views addObject:view];
	}
	if (mainLayer.superlayer != nil) {
		[mainLayer removeFromSuperlayer];
	}

	[view.layer addSublayer:mainLayer];
	[view setNeedsLayout];

	_currentView = view;
	return mainLayer;
}

- (instancetype)init {
	if (self = [super init]) {
		[self setDefaultValues];
	}
	return self;
}

- (void)setDefaultValues {
	while (self.subviews.firstObject) {
		[self.subviews.firstObject removeFromSuperview];
	}
	self.multipleTouchEnabled = YES;

	_renderingLayer = nil;
	_windowId = 0;
	_touches.reserve(MAX_TOUCH_COUNT);
	for (int i = 0; i < MAX_TOUCH_COUNT; ++i) {
		_touches.push_back(nil);
	}
	_propsUpdated = false;
	_instanceCallbackRegistered = false;
	_windowName = @"";
	_addingGodotView = false;
    _attachmentGeneration = 0;
    _attachmentRequest = 0;
}

//Setter method
- (void)setWindowName:(NSString *)n {
	if (n == nil) {
		n = @"";
	}
	if ([_windowName isEqualToString:n]) {
		return;
	}

	NSLog(@"Setting windowName to: %@", n);
	_windowName = n;
	if (self.superview) {
		// Remove and add again
		[self removeFromGodotView:true unregister:true];
	}
}

//Getter method
- (NSString *)windowName {
	NSLog(@"Returning windowName: %@", _windowName);
	return _windowName;
}

- (void)setNeedsLayout {
	[super setNeedsLayout];
	[self invalidateIntrinsicContentSize];
}

- (CGSize)intrinsicContentSize {
	return [self sizeThatFits:CGSizeMake(CGFLOAT_MAX, CGFLOAT_MAX)];
}

- (void)deinit {
}

- (void)addToGodotView {
	NSLog(@"RTNGodotView: Adding Godot View: %@, windowName: %@", self, _windowName);

	godot::GodotInstance *instance = GodotModule::get_singleton()->get_instance();

	if (!_instanceCallbackRegistered) {
		GodotModule::get_singleton()->unregisterWindowUpdateCallback((__bridge void *)self);
		std::string newWinName = [_windowName UTF8String];
		GodotModule::get_singleton()->registerWindowUpdateCallback(newWinName, (__bridge void *)self, [self](bool adding) {
			if (adding) {
				dispatch_async(dispatch_get_main_queue(), ^{
					NSLog(@"RTNGodotView: Adding Godot View from Window Update Callback: %@", self);
					[self addToGodotView];
				});
			} else {
				dispatch_async(dispatch_get_main_queue(), ^{
					NSLog(@"RTNGodotView: Removing Godot View from Window Update Callback: %@", self);
					[self removeFromGodotView:false unregister:false];
				});
			} }, nullptr);
		_instanceCallbackRegistered = true;
	}

	if (!instance) {
		// Cannot continue without a Godot instance
		NSLog(@"RTNGodotView: Godot instance not started yet.");
		return;
	}

	if (_windowId > 0) {
		NSLog(@"RTNGodotView: Window already configured");
		return;
	}

	if (_addingGodotView) return;
    _addingGodotView = true;
    const uint64_t generation = GodotModule::get_singleton()->generation();
    const uint64_t request = ++_attachmentRequest;
	if ([@"" isEqualToString:_windowName]) {
		// Set up the main window

		GodotModule::get_singleton()->runOnGodotThread([=]() {
            if (generation != GodotModule::get_singleton()->generation() || !GodotModule::get_singleton()->get_instance()) return;
			godot::MainLoop *mainLoop = godot::Engine::get_singleton()->get_main_loop();
			godot::SceneTree *sceneTree = godot::Object::cast_to<godot::SceneTree>(mainLoop);
			if (!sceneTree) {
				NSLog(@"RTNGodotView: Unable to get SceneTree from Godot!");
				return;
			}
			godot::Window *newWindow = sceneTree->get_root();
            const uint64_t newWindowId = newWindow->get_instance_id();
			dispatch_async(dispatch_get_main_queue(), ^{
				if (generation != GodotModule::get_singleton()->generation() || request != self->_attachmentRequest) return;
                self->_attachmentGeneration = generation;
                self->_windowId = newWindowId;
				self->_renderingLayer = [RTNGodotView addMainLayerToGodotView:self];
				[self setNeedsLayout];
				self->_addingGodotView = false;
			});
		});

	} else {
		// Subwindow case
		GodotModule::get_singleton()->runOnGodotThread([=]() {
            if (generation != GodotModule::get_singleton()->generation() || !GodotModule::get_singleton()->get_instance()) return;
			godot::MainLoop *mainLoop = godot::Engine::get_singleton()->get_main_loop();
			godot::SceneTree *sceneTree = godot::Object::cast_to<godot::SceneTree>(mainLoop);
			if (!sceneTree) {
				NSLog(@"RTNGodotView: Unable to get SceneTree from Godot!");
				return;
			}

			std::string newWinName = [_windowName UTF8String];
			godot::Node *node = sceneTree->get_root()->find_child(godot::String::utf8(newWinName.c_str()), true, false);
			godot::Window *newWindow = godot::Object::cast_to<godot::Window>(node);

			if (!newWindow) {
				NSLog(@"RTNGodotView: Godot Window not valid: 0x%p", newWindow);
				dispatch_async(dispatch_get_main_queue(), ^{
					self->_addingGodotView = false;
				});
				return;
			}

			CGRect screen = [[UIScreen mainScreen] bounds];
			CALayer *newRenderingLayer = nil;

			godot::Ref<godot::RenderingNativeSurfaceApple> appleSurface = godot::RenderingNativeSurfaceApple::create(0);
			newRenderingLayer = (__bridge CALayer *)(void *)appleSurface->get_layer();
			newRenderingLayer.bounds = CGRectMake(0, 0, screen.size.width, screen.size.height);
			newRenderingLayer.position = CGPointMake(0, 0);
			newRenderingLayer.anchorPoint = CGPointMake(0, 0);
			newRenderingLayer.contentsScale = GodotModule::get_singleton()->get_content_scale_factor();

			godot::RenderingNativeSurface *ptr = godot::Object::cast_to<godot::RenderingNativeSurface>(appleSurface.ptr());
			godot::Ref<godot::RenderingNativeSurface> nativeSurface(ptr);

			const uint64_t newWindowId = newWindow->get_instance_id();
            newWindow->set_visible(true);
			newWindow->set_native_surface(nativeSurface);
			godot::Callable exited_cb = GodotModule::get_singleton()->create_callable([=](const godot::Variant **p_arguments, int p_argcount, godot::Variant &r_return_value, GDExtensionCallError &r_call_error) {
				// Window is now removed, needs relayout
				dispatch_async(dispatch_get_main_queue(), ^{
					if (self->_renderingLayer == newRenderingLayer) {
						[newRenderingLayer removeFromSuperlayer];
						self->_renderingLayer = nil;
					}
					self->_windowId = 0;
					[self setNeedsLayout];
				});
			});
			newWindow->connect("tree_exited", exited_cb);

			dispatch_async(dispatch_get_main_queue(), ^{
				if (generation != GodotModule::get_singleton()->generation() || request != self->_attachmentRequest) return;
                self->_attachmentGeneration = generation;
                self->_windowId = newWindowId;
				self->_renderingLayer = newRenderingLayer;
				[self.layer addSublayer:self->_renderingLayer];
				[self setNeedsLayout];
				self->_addingGodotView = false;
			});
		});
	}
}

- (void)removeFromGodotView:(bool)addAfter unregister:(bool)unregister {
    NSMutableSet<UITouch *> *activeTouches = [NSMutableSet set];
    for (UITouch *touch : _touches) if (touch) [activeTouches addObject:touch];
    [self forwardTouches:activeTouches phase:3];

	NSLog(@"RTNGodotView: Removing Godot View: %@, windowName: %@, addAfter: %d", self, _windowName, addAfter);
    ++_attachmentRequest;
    _addingGodotView = false;
	if (unregister) {
		GodotModule::get_singleton()->unregisterWindowUpdateCallback((__bridge void *)self);
		self->_instanceCallbackRegistered = false;
	}
	void (^removeBlock)() = ^() {
		if (![@"" isEqualToString:self->_windowName]) {
			// Only remove if it is not the main window
			if (self->_renderingLayer) {
				if (self->_renderingLayer.superlayer == self.layer) {
					// Only remove, if it is our sublayer
					[self->_renderingLayer removeFromSuperlayer];
				}
			}
		} else {
			// If it is the main window, then request removal from the manager
			[RTNGodotView removeMainLayerFromGodotView:self];
		}
		self->_windowId = 0;
		self->_renderingLayer = nullptr;
		if (addAfter) {
			[self addToGodotView];
		}
	};
	if ([NSThread isMainThread]) {
		removeBlock();
	} else {
		if (!unregister) {
			// This should only happen when the Godot instance is being stopped
			dispatch_sync(dispatch_get_main_queue(), [removeBlock]() {
				removeBlock();
			});
		} else {
			dispatch_async(dispatch_get_main_queue(), [removeBlock]() {
				removeBlock();
			});
		}
	}
}

- (void)layoutSubviews {
    [super layoutSubviews];
    if (!_windowId || !_renderingLayer) return;
    auto *module = GodotModule::get_singleton();
    const uint64_t generation = _attachmentGeneration;
    const uint64_t windowId = _windowId;
    const double scale = module->get_content_scale_factor();
    const CGRect bounds = CGRectMake(0, 0, godot::MAX(10, self.bounds.size.width), godot::MAX(10, self.bounds.size.height));
    _renderingLayer.bounds = bounds;
    const int width = bounds.size.width * scale;
    const int height = bounds.size.height * scale;
    module->runOnGodotThread([=]() {
        if (generation != module->generation() || !module->get_instance()) return;
        if (!godot::UtilityFunctions::is_instance_id_valid(windowId)) return;
        auto *window = godot::Object::cast_to<godot::Window>(godot::UtilityFunctions::instance_from_id(windowId));
        auto *display = godot::DisplayServerEmbedded::get_singleton();
        if (window && display) display->resize_window(godot::Vector2i(width, height), window->get_window_id());
    });
}

- (int)getTouchId:(UITouch *)touch {
	int first = -1;
	for (int i = 0; i < MAX_TOUCH_COUNT; ++i) {
		if (first == -1 && (i >= _touches.size() || _touches[i] == nil)) {
			first = i;
			continue;
		}
		if (_touches[i] == touch) {
			return i;
		}
	}

	if (first != -1) {
		_touches[first] = touch;
		return first;
	}

	return -1;
}

- (void)removeTouchId:(int)touchId {
	_touches[touchId] = nil;
}

// Capture UIKit state on main; resolve Godot objects only on the engine thread.
- (void)forwardTouches:(NSSet<UITouch *> *)touches phase:(int)phase {
    const uint64_t generation = _attachmentGeneration;
    const uint64_t windowId = _windowId;
    if (!windowId || !_renderingLayer) return;
    const CGRect frame = _renderingLayer.frame;
    const double scale = GodotModule::get_singleton()->get_content_scale_factor();
    for (UITouch *touch in touches) {
        CGPoint point = [touch locationInView:self];
        if (phase == 0 && !CGRectContainsPoint(frame, point)) continue;
        int touchId = -1;
        if (phase == 0) touchId = [self getTouchId:touch];
        else for (int i = 0; i < MAX_TOUCH_COUNT; ++i) if (_touches[i] == touch) { touchId = i; break; }
        if (touchId < 0) continue;
        if (phase >= 2) [self removeTouchId:touchId];
        CGPoint previous = [touch previousLocationInView:self];
        point.x = (point.x - frame.origin.x) * scale;
        point.y = (point.y - frame.origin.y) * scale;
        previous.x = (previous.x - frame.origin.x) * scale;
        previous.y = (previous.y - frame.origin.y) * scale;
        const bool doubleTap = touch.tapCount > 1;
        const float pressure = touch.maximumPossibleForce > 0 ? touch.force / touch.maximumPossibleForce : 0;
        GodotModule::get_singleton()->runOnGodotThread([=]() {
            auto *module = GodotModule::get_singleton();
            if (generation != module->generation() || !module->get_instance()) return;
            if (!godot::UtilityFunctions::is_instance_id_valid(windowId)) return;
            auto *window = godot::Object::cast_to<godot::Window>(godot::UtilityFunctions::instance_from_id(windowId));
            auto *display = godot::DisplayServerEmbedded::get_singleton();
            if (!window || !display) return;
            const auto id = window->get_window_id();
            if (phase == 3) display->touches_canceled(touchId, id);
            else if (phase == 1) display->call("touch_drag", touchId, previous.x, previous.y, point.x, point.y, pressure, godot::Vector2(), id);
            else display->call("touch_press", touchId, point.x, point.y, phase == 0, doubleTap, id);
        });
    }
}
- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { [self forwardTouches:touches phase:0]; }
- (void)touchesMoved:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { [self forwardTouches:touches phase:1]; }
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { [self forwardTouches:touches phase:2]; }
- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { [self forwardTouches:touches phase:3]; }

- (void)willMoveToSuperview:(UIView *)newSuperview {
	NSLog(@"RTNGodotView: %@ will move to superview %@", self, newSuperview);
	if (newSuperview == nil) {
		[self removeFromGodotView:false unregister:true];
	} else {
		[self addToGodotView];
	}
}

- (void)updateProps:(Props::Shared const &)props oldProps:(Props::Shared const &)oldProps {
	const auto &oldViewProps = *std::static_pointer_cast<RTNGodotViewProps const>(oldProps);
	const auto &newViewProps = *std::static_pointer_cast<RTNGodotViewProps const>(props);

	// Handle your props here
	if ((oldProps == nullptr && props != nullptr) ||
			((oldProps != nullptr && props != nullptr) && (oldViewProps.windowName != newViewProps.windowName))) {
		[self setWindowName:[NSString stringWithUTF8String:newViewProps.windowName.c_str()]];
	}
	//[super updateProps:props oldProps:oldProps];
}

- (void)didMoveToSuperview:(UIView *)newSuperview {
	NSLog(@"RTNGodotView: %@ did move to superview %@", self, newSuperview);
}

+ (ComponentDescriptorProvider)componentDescriptorProvider {
	return concreteComponentDescriptorProvider<RTNGodotViewComponentDescriptor>();
}

@end
