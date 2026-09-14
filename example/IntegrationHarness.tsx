/* eslint-disable no-void -- UI handlers intentionally consume handled promises. */
import React, {useEffect, useRef, useState} from 'react';
import {
  AppState,
  Button,
  DevSettings,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  Platform,
} from 'react-native';
import {
  RTNGodot,
  RTNGodotView,
  runOnGodotThread,
} from '@borndotcom/react-native-godot';
import {scheduleOnRN} from 'react-native-worklets';
import {
  bundleDirectory,
  documentDirectory,
  copyAsync,
  readAsStringAsync,
  writeAsStringAsync,
  deleteAsync,
} from 'expo-file-system/legacy';

declare const process: {env: Record<string, string | undefined>};
declare global {
  var __godotHarnessBootstrapped: boolean | undefined;
}

export default function IntegrationHarness() {
  const [status, setStatus] = useState('Ready to start');
  const [attached, setAttached] = useState(true);
  const [sheet, setSheet] = useState(false);
  const [busy, setBusy] = useState(false);
  const [event, setEvent] = useState('No scene event yet');
  const receiveEvent = (payload: string) => {
    console.info('[IntegrationHarnessEvent]', payload);
    setEvent(payload);
  };
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {
      if (state === 'active' && !sheet) RTNGodot.resume();
      else RTNGodot.pause();
    });
    if (sheet) RTNGodot.pause();
    else RTNGodot.resume();
    return () => subscription.remove();
  }, [sheet]);
  const load = (variant: 'a' | 'b') => {
    const name = variant === 'a' ? 'GodotTest' : 'GodotTest2';
    const uri =
      Platform.OS === 'android'
        ? `${documentDirectory}${name}.pck`
        : `${bundleDirectory}${name}.pck`;
    const path = decodeURIComponent(uri.replace(/^file:\/\//, ''));
    const compatibility =
      Platform.OS === 'android' &&
      process.env.EXPO_PUBLIC_GODOT_HARNESS_RENDERER === 'compatibility';
    const driver =
      Platform.OS === 'android'
        ? compatibility
          ? 'opengl3'
          : 'vulkan'
        : 'metal';
    const method = compatibility ? 'gl_compatibility' : 'mobile';
    const operation = async () => {
      if (Platform.OS === 'android')
        await copyAsync({from: `asset:///${name}.pck`, to: uri});
      RTNGodot.resume();
      await runOnGodotThread(() => {
        'worklet';
        if (RTNGodot.getInstance()) RTNGodot.destroyInstance();
        if (
          !RTNGodot.createInstance([
            '--main-pack',
            path,
            '--display-driver',
            'embedded',
            '--rendering-driver',
            driver,
            '--rendering-method',
            method,
            '--audio-driver',
            'Dummy',
            '--max-fps',
            '30',
          ])
        ) {
          throw new Error('Engine creation failed');
        }
      });
      // Let the engine load the scene before reading its state.
      for (let attempt = 0; attempt < 100; attempt++) {
        const result = await runOnGodotThread(() => {
          'worklet';
          const api = RTNGodot.API();
          const scene = api.Engine.get_main_loop()
            .get_root()
            .find_child('Harness', true, false);
          if (!scene) return null;
          const sceneStatus = JSON.parse(String(scene.status_json()));
          if (sceneStatus.frames < 3) return null;
          const callback = (payload: unknown) => {
            'worklet';
            scheduleOnRN(receiveEvent, String(payload));
          };
          scene.host_event.connect(callback);
          scene.echo_event('你好，G 🐈');
          return {
            scene: sceneStatus,
            engine: api.Engine.get_version_info().get('string'),
            renderer: {
              driver: api.RenderingServer.get_current_rendering_driver_name(),
              method: api.RenderingServer.get_current_rendering_method(),
            },
            native: RTNGodot.getSessionStatus(),
          };
        });
        if (result) return result;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
      throw new Error('Scene startup timed out');
    };
    const result = queue.current.then(operation);
    queue.current = result.catch(() => {});
    return result;
  };
  const run = async (cycles: number) => {
    if (busy) return;
    setBusy(true);
    try {
      for (let cycle = 0; cycle < cycles; cycle++) {
        const result = await load(cycle % 2 === 0 ? 'a' : 'b');
        const message = JSON.stringify({cycle: cycle + 1, ...result});
        console.info(
          '[IntegrationHarness]',
          message,
          JSON.stringify(RTNGodot.getProcessMetrics()),
        );
        setStatus(message);
      }
    } catch (error) {
      setStatus(String(error));
    } finally {
      setBusy(false);
    }
  };
  const cycleSurfaces = async () => {
    if (busy) return;
    setBusy(true);
    const before = RTNGodot.getSessionStatus();
    try {
      for (let cycle = 1; cycle <= 20; cycle++) {
        setAttached(false);
        await new Promise(resolve => setTimeout(resolve, 150));
        setAttached(true);
        await new Promise(resolve => setTimeout(resolve, 150));
        const after = RTNGodot.getSessionStatus();
        if (after.generation !== before.generation)
          throw new Error('Surface attachment restarted the engine');
        const frames = await runOnGodotThread(() => {
          'worklet';
          return RTNGodot.API().Engine.get_process_frames();
        });
        const message = JSON.stringify({
          surfaceCycle: cycle,
          frames,
          native: after,
          memory: RTNGodot.getProcessMetrics(),
        });
        console.info('[IntegrationHarness]', message);
        setStatus(message);
      }
    } catch (error) {
      setStatus(String(error));
    } finally {
      setBusy(false);
    }
  };
  const checkRecovery = async () => {
    const compatibility =
      Platform.OS === 'android' &&
      process.env.EXPO_PUBLIC_GODOT_HARNESS_RENDERER === 'compatibility';
    const driver =
      Platform.OS === 'android'
        ? compatibility
          ? 'opengl3'
          : 'vulkan'
        : 'metal';
    const method = compatibility ? 'gl_compatibility' : 'mobile';
    try {
      await runOnGodotThread(() => {
        'worklet';
        if (RTNGodot.getInstance()) RTNGodot.destroyInstance();
        const invalid = RTNGodot.createInstance([
          '--main-pack',
          '/missing-harness-pack.pck',
          '--display-driver',
          'embedded',
          '--rendering-driver',
          driver,
          '--rendering-method',
          method,
          '--audio-driver',
          'Dummy',
        ]);
        if (invalid) throw new Error('Missing pack was accepted');
      });
      const recovered = await load('a');
      console.info('[IntegrationHarnessRecovery]', JSON.stringify(recovered));
      setStatus('Missing pack rejected; valid pack recovered.');
    } catch (error) {
      console.error('[IntegrationHarnessRecovery]', String(error));
      setStatus(String(error));
    }
  };
  useEffect(() => {
    if (globalThis.__godotHarnessBootstrapped) {
      console.info(
        '[IntegrationHarnessFastRefresh]',
        JSON.stringify(RTNGodot.getSessionStatus()),
      );
      return;
    }
    globalThis.__godotHarnessBootstrapped = true;
    if (process.env.EXPO_PUBLIC_GODOT_HARNESS_RELOAD === '1') {
      void (async () => {
        const marker = `${documentDirectory}harness-runtime-reload.json`;
        const previous = await readAsStringAsync(marker).catch(() => '');
        const result = await load('a');
        if (previous) {
          const before = JSON.parse(previous).generation;
          if (result.native.generation <= before)
            throw new Error('Full JS reload did not restart the engine');
          console.info(
            '[IntegrationHarnessRuntimeReload]',
            JSON.stringify({before, after: result.native, scene: result.scene}),
          );
          await deleteAsync(marker, {idempotent: true});
          setStatus('Full JavaScript reload recreated the engine.');
        } else {
          await writeAsStringAsync(marker, JSON.stringify(result.native));
          DevSettings.reload();
        }
      })().catch(error => {
        console.error('[IntegrationHarnessRuntimeReload]', String(error));
        setStatus(String(error));
      });
      return;
    }
    if (process.env.EXPO_PUBLIC_GODOT_HARNESS_RECOVERY === '1') {
      void checkRecovery();
      return;
    }
    if (process.env.EXPO_PUBLIC_GODOT_HARNESS_SURFACES === '20') {
      void load('a')
        .then(cycleSurfaces)
        .catch(error => setStatus(String(error)));
      return;
    }
    if (process.env.EXPO_PUBLIC_GODOT_HARNESS_CYCLES === '20') {
      void run(20);
      return;
    }
    void load('a')
      .then(result => {
        console.info('[IntegrationHarness]', JSON.stringify(result));
        setStatus(JSON.stringify(result));
      })
      .catch(error => setStatus(String(error)));
  }, []);
  return (
    <View style={styles.root}>
      {attached ? <RTNGodotView style={StyleSheet.absoluteFill} /> : null}
      <ScrollView style={styles.controls}>
        <Text selectable>{status}</Text>
        <Text accessibilityLabel={`Scene event: ${event}`}>{event}</Text>
        <TextInput
          accessibilityLabel="Native input"
          placeholder="Type while the world runs"
          style={styles.input}
        />
        <Button
          title="Load blue pack"
          disabled={busy}
          onPress={() => {
            void load('a')
              .then(x => setStatus(JSON.stringify(x)))
              .catch(x => setStatus(String(x)));
          }}
        />
        <Button
          title="Load red pack"
          disabled={busy}
          onPress={() => {
            void load('b')
              .then(x => setStatus(JSON.stringify(x)))
              .catch(x => setStatus(String(x)));
          }}
        />
        <Button
          title="Run 20 pack/restart cycles"
          disabled={busy}
          onPress={() => {
            void run(20);
          }}
        />
        <Button
          title={attached ? 'Detach surface' : 'Attach surface'}
          onPress={() => setAttached(!attached)}
        />
        <Button
          title="Run 20 surface cycles"
          disabled={busy}
          onPress={() => {
            void cycleSurfaces();
          }}
        />
        <Button
          title="Check missing-pack recovery"
          disabled={busy}
          onPress={() => {
            void checkRecovery();
          }}
        />
        <Button
          title="Reload JavaScript runtime"
          onPress={() => DevSettings.reload()}
        />
        <Button
          title="Check scene event round trip"
          onPress={() => {
            void runOnGodotThread(() => {
              'worklet';
              const scene = RTNGodot.API()
                .Engine.get_main_loop()
                .get_root()
                .find_child('Harness', true, false);
              scene.echo_event('你好，G 🐈');
            }).catch(error => setStatus(String(error)));
          }}
        />
        <Button title="Open native sheet" onPress={() => setSheet(true)} />
      </ScrollView>
      <Modal
        visible={sheet}
        presentationStyle="pageSheet"
        onRequestClose={() => setSheet(false)}>
        <View style={styles.controls}>
          <Text>The world is paused.</Text>
          <Button title="Return" onPress={() => setSheet(false)} />
        </View>
      </Modal>
    </View>
  );
}
const styles = StyleSheet.create({
  root: {flex: 1},
  controls: {
    marginTop: 60,
    padding: 16,
    maxHeight: '55%',
    backgroundColor: 'white',
  },
  input: {borderWidth: 1, padding: 12},
});
