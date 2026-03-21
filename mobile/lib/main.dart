import 'dart:async';
import 'dart:typed_data';

import 'package:camera/camera.dart';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

const defaultWsUrl = 'ws://benchagent-pi:8420/camera/ws';
const targetFps = 10;
const jpegQuality = 70;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final cameras = await availableCameras();
  runApp(BenchCameraApp(cameras: cameras));
}

class BenchCameraApp extends StatelessWidget {
  final List<CameraDescription> cameras;

  const BenchCameraApp({super.key, required this.cameras});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'BenchAgent Camera',
      theme: ThemeData.dark(useMaterial3: true).copyWith(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.teal,
          brightness: Brightness.dark,
        ),
      ),
      home: CameraStreamPage(cameras: cameras),
    );
  }
}

class CameraStreamPage extends StatefulWidget {
  final List<CameraDescription> cameras;

  const CameraStreamPage({super.key, required this.cameras});

  @override
  State<CameraStreamPage> createState() => _CameraStreamPageState();
}

class _CameraStreamPageState extends State<CameraStreamPage>
    with WidgetsBindingObserver {
  CameraController? _cameraController;
  WebSocketChannel? _channel;
  Timer? _frameTimer;

  bool _streaming = false;
  bool _wsConnected = false;
  int _framesSent = 0;
  String _wsUrl = defaultWsUrl;
  String? _error;
  int _selectedCameraIndex = 0;

  final _urlController = TextEditingController(text: defaultWsUrl);

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (widget.cameras.isNotEmpty) {
      _initCamera(_selectedCameraIndex);
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _stopStreaming();
    _cameraController?.dispose();
    _urlController.dispose();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (_cameraController == null || !_cameraController!.value.isInitialized) {
      return;
    }
    if (state == AppLifecycleState.inactive) {
      _stopStreaming();
      _cameraController?.dispose();
      _cameraController = null;
    } else if (state == AppLifecycleState.resumed) {
      _initCamera(_selectedCameraIndex);
    }
  }

  Future<void> _initCamera(int index) async {
    if (widget.cameras.isEmpty) return;

    _cameraController?.dispose();
    _selectedCameraIndex = index;

    final controller = CameraController(
      widget.cameras[index],
      ResolutionPreset.medium,
      enableAudio: false,
      imageFormatGroup: ImageFormatGroup.jpeg,
    );

    try {
      await controller.initialize();
      if (!mounted) return;
      setState(() {
        _cameraController = controller;
        _error = null;
      });
    } catch (e) {
      setState(() => _error = 'Camera init failed: $e');
    }
  }

  void _toggleStreaming() {
    if (_streaming) {
      _stopStreaming();
    } else {
      _startStreaming();
    }
  }

  void _startStreaming() {
    if (_cameraController == null || !_cameraController!.value.isInitialized) {
      setState(() => _error = 'Camera not ready');
      return;
    }

    _wsUrl = _urlController.text.trim();
    if (_wsUrl.isEmpty) {
      setState(() => _error = 'WebSocket URL is required');
      return;
    }

    try {
      _channel = WebSocketChannel.connect(Uri.parse(_wsUrl));
      _channel!.stream.listen(
        (_) {},
        onError: (e) {
          setState(() {
            _error = 'WebSocket error: $e';
            _wsConnected = false;
            _streaming = false;
          });
          _frameTimer?.cancel();
        },
        onDone: () {
          setState(() {
            _wsConnected = false;
            _streaming = false;
          });
          _frameTimer?.cancel();
        },
      );

      setState(() {
        _streaming = true;
        _wsConnected = true;
        _framesSent = 0;
        _error = null;
      });

      final interval = Duration(milliseconds: 1000 ~/ targetFps);
      _frameTimer = Timer.periodic(interval, (_) => _captureAndSend());
    } catch (e) {
      setState(() => _error = 'Failed to connect: $e');
    }
  }

  void _stopStreaming() {
    _frameTimer?.cancel();
    _frameTimer = null;
    _channel?.sink.close();
    _channel = null;
    if (mounted) {
      setState(() {
        _streaming = false;
        _wsConnected = false;
      });
    }
  }

  Future<void> _captureAndSend() async {
    if (!_streaming || _cameraController == null) return;

    try {
      final xFile = await _cameraController!.takePicture();
      final Uint8List bytes = await xFile.readAsBytes();

      if (bytes.length < 100) return; // skip tiny/invalid frames

      _channel?.sink.add(bytes);
      if (mounted) {
        setState(() => _framesSent++);
      }
    } catch (e) {
      // Frame capture can occasionally fail, don't crash the stream
    }
  }

  void _switchCamera() {
    if (widget.cameras.length < 2) return;
    final wasStreaming = _streaming;
    if (wasStreaming) _stopStreaming();

    final next = (_selectedCameraIndex + 1) % widget.cameras.length;
    _initCamera(next).then((_) {
      if (wasStreaming) _startStreaming();
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('BenchAgent Camera'),
        actions: [
          if (widget.cameras.length > 1)
            IconButton(
              icon: const Icon(Icons.cameraswitch),
              onPressed: _switchCamera,
              tooltip: 'Switch camera',
            ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            // Camera preview
            Expanded(
              child: _buildCameraPreview(),
            ),

            // Status bar
            _buildStatusBar(),

            // WebSocket URL input
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
              child: TextField(
                controller: _urlController,
                enabled: !_streaming,
                decoration: InputDecoration(
                  labelText: 'Pi Worker WebSocket URL',
                  hintText: defaultWsUrl,
                  border: const OutlineInputBorder(),
                  prefixIcon: const Icon(Icons.link),
                  suffixIcon: !_streaming
                      ? IconButton(
                          icon: const Icon(Icons.restore),
                          onPressed: () =>
                              _urlController.text = defaultWsUrl,
                          tooltip: 'Reset to default',
                        )
                      : null,
                ),
                style: const TextStyle(fontSize: 13),
              ),
            ),

            // Stream toggle button
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
              child: SizedBox(
                width: double.infinity,
                height: 56,
                child: FilledButton.icon(
                  onPressed: widget.cameras.isEmpty ? null : _toggleStreaming,
                  icon: Icon(_streaming ? Icons.stop : Icons.play_arrow),
                  label: Text(
                    _streaming ? 'Stop Streaming' : 'Start Streaming',
                    style: const TextStyle(fontSize: 18),
                  ),
                  style: FilledButton.styleFrom(
                    backgroundColor:
                        _streaming ? Colors.red.shade700 : Colors.teal,
                  ),
                ),
              ),
            ),

            // Error display
            if (_error != null)
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                child: Text(
                  _error!,
                  style: TextStyle(color: Colors.red.shade300, fontSize: 13),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildCameraPreview() {
    if (widget.cameras.isEmpty) {
      return const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.no_photography, size: 64, color: Colors.grey),
            SizedBox(height: 12),
            Text('No cameras available', style: TextStyle(color: Colors.grey)),
          ],
        ),
      );
    }

    if (_cameraController == null || !_cameraController!.value.isInitialized) {
      return const Center(child: CircularProgressIndicator());
    }

    return ClipRect(
      child: FittedBox(
        fit: BoxFit.cover,
        child: SizedBox(
          width: _cameraController!.value.previewSize!.height,
          height: _cameraController!.value.previewSize!.width,
          child: CameraPreview(_cameraController!),
        ),
      ),
    );
  }

  Widget _buildStatusBar() {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      color: Colors.black26,
      child: Row(
        children: [
          // Connection status indicator
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: _wsConnected ? Colors.greenAccent : Colors.grey,
            ),
          ),
          const SizedBox(width: 8),
          Text(
            _wsConnected ? 'Connected' : 'Disconnected',
            style: TextStyle(
              color: _wsConnected ? Colors.greenAccent : Colors.grey,
              fontWeight: FontWeight.w500,
            ),
          ),
          const Spacer(),
          if (_streaming) ...[
            const Icon(Icons.fiber_manual_record,
                color: Colors.redAccent, size: 14),
            const SizedBox(width: 4),
            Text(
              '$_framesSent frames sent',
              style: const TextStyle(color: Colors.white70, fontSize: 13),
            ),
          ],
        ],
      ),
    );
  }
}
