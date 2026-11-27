import 'dart:async';
import 'dart:convert';
import 'dart:js_interop';
import 'package:http/http.dart' as http;
import 'package:material_ui/material_ui.dart';
import 'package:web/web.dart' as web;
import 'api.dart';

/// Session-only consent. Coordinates are never written to browser storage.
class NearbyController extends ChangeNotifier {
  static final instance = NearbyController._();
  NearbyController._() {
    _visibility = ((web.Event event) {
      if (web.document.visibilityState != 'visible') {
        stop('화면을 벗어나 위치 공유를 껐어요. 다시 켜려면 버튼을 눌러 주세요.');
      }
    }).toJS;
    _pagehide = ((web.Event event) => stop()).toJS;
    web.document.addEventListener('visibilitychange', _visibility);
    web.window.addEventListener('pagehide', _pagehide);
  }
  late final JSFunction _visibility, _pagehide;
  bool active = false, starting = false, _sampling = false;
  String message = '위치 공유가 꺼져 있어요.';
  int alertSerial = 0, _epoch = 0;
  String? _lease;
  String _origin = '', _token = '';
  Timer? _poll, _expiry;

  Future<Map<String, dynamic>> _request(
    String origin,
    String token,
    String path,
    Map<String, dynamic> body,
  ) async {
    final result = await http
        .post(
          Uri.parse('$origin/api/nearby/$path'),
          headers: {
            'Authorization': 'Bearer $token',
            'Content-Type': 'application/json',
          },
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 12));
    if (result.statusCode >= 400) {
      final data = jsonDecode(result.body);
      throw Exception(
        data is Map && data['detail'] is String
            ? data['detail']
            : '근처 알림에 연결하지 못했어요.',
      );
    }
    return Map<String, dynamic>.from(Api.check(result));
  }

  Future<void> _closeLease(String origin, String token, String lease) async {
    try {
      // Best effort on page hide/unload; the server also expires stale presence.
      await web.window
          .fetch(
            '$origin/api/nearby/stop'.toJS,
            web.RequestInit(
              method: 'POST',
              keepalive: true,
              headers: (web.Headers()
                ..set('Authorization', 'Bearer $token')
                ..set('Content-Type', 'application/json')),
              body: jsonEncode({'lease': lease}).toJS,
            ),
          )
          .toDart;
    } catch (_) {
      /* Server TTL removes an unreachable lease. */
    }
  }

  Future<void> start() async {
    if (active || starting) return;
    if (!web.window.isSecureContext ||
        web.document.visibilityState != 'visible') {
      message = 'HTTPS로 열린 앱 화면에서 위치 공유를 켜 주세요.';
      notifyListeners();
      return;
    }
    final epoch = ++_epoch;
    final origin = Api.uri('/').origin, token = Api.token;
    starting = true;
    message = '위치 공유를 준비하고 있어요.';
    notifyListeners();
    try {
      final result = await _request(origin, token, 'start', {'consent': true});
      final lease = result['lease'] as String;
      if (epoch != _epoch) {
        unawaited(_closeLease(origin, token, lease));
        return;
      }
      _origin = origin;
      _token = token;
      _lease = lease;
      active = true;
      starting = false;
      _expiry = Timer(
        Duration(seconds: result['duration_seconds'] as int),
        () => stop('15분이 지나 위치 공유를 껐어요. 원하면 다시 켜 주세요.'),
      );
      _poll = Timer.periodic(
        const Duration(seconds: 30),
        (_) => _sample(epoch),
      );
      message = '브라우저에서 위치 접근을 허용해 주세요.';
      notifyListeners();
      unawaited(_sample(epoch));
    } catch (error) {
      if (epoch == _epoch) {
        stop(
          error is Exception && error is! TimeoutException
              ? error.toString().replaceFirst('Exception: ', '')
              : '위치 공유를 시작하지 못했어요. 로그인과 서버 연결을 확인해 주세요.',
        );
      }
    }
  }

  Future<void> _sample(int epoch) async {
    if (epoch != _epoch || !active || _sampling) return;
    if (web.document.visibilityState != 'visible' ||
        Api.token != _token ||
        Api.uri('/').origin != _origin) {
      stop('화면이나 계정 연결이 바뀌어 위치 공유를 껐어요.');
      return;
    }
    _sampling = true;
    try {
      final pending = Completer<web.GeolocationPosition>();
      web.window.navigator.geolocation.getCurrentPosition(
        ((web.GeolocationPosition position) {
          if (!pending.isCompleted) pending.complete(position);
        }).toJS,
        ((web.GeolocationPositionError error) {
          if (!pending.isCompleted) pending.completeError(error.code);
        }).toJS,
        web.PositionOptions(
          enableHighAccuracy: false,
          timeout: 12000,
          maximumAge: 15000,
        ),
      );
      final position = await pending.future.timeout(
        const Duration(seconds: 20),
      );
      if (epoch != _epoch || !active) return;
      final coords = position.coords;
      if (!coords.accuracy.isFinite ||
          coords.accuracy > 250 ||
          (DateTime.now().millisecondsSinceEpoch - position.timestamp).abs() >
              30000) {
        stop('현재 위치가 정확하지 않아 공유하지 않았어요. 위치 설정을 확인한 뒤 다시 켜 주세요.');
        return;
      }
      final result = await _request(_origin, _token, 'update', {
        'lease': _lease,
        // Roughly 100m resolution before the coordinates leave the device.
        'latitude': double.parse(coords.latitude.toStringAsFixed(3)),
        'longitude': double.parse(coords.longitude.toStringAsFixed(3)),
        'accuracy': coords.accuracy,
      });
      if (epoch != _epoch || !active) return;
      message = result['nearby'] == true
          ? '약 1km 안에서 위치 공유를 켠 사용자가 있어요.'
          : '근처에서 위치 공유를 켠 사용자를 기다리고 있어요.';
      if (result['notify'] == true) alertSerial++;
      notifyListeners();
    } catch (error) {
      if (epoch == _epoch) {
        stop(
          error is int && error == 1
              ? '위치 권한이 허용되지 않아 공유를 껐어요. 브라우저 설정에서 허용한 뒤 다시 켜 주세요.'
              : '위치 또는 서버 연결을 확인하지 못해 공유를 껐어요. 잠시 후 다시 켜 주세요.',
        );
      }
    } finally {
      if (epoch == _epoch) _sampling = false;
    }
  }

  void stop([String reason = '위치 공유를 껐어요. 연결이 끊긴 경우에도 서버에서 90초 안에 만료돼요.']) {
    final lease = _lease, origin = _origin, token = _token;
    ++_epoch;
    _lease = null;
    _token = '';
    _origin = '';
    _poll?.cancel();
    _expiry?.cancel();
    _poll = null;
    _expiry = null;
    active = false;
    starting = false;
    _sampling = false;
    message = reason;
    notifyListeners();
    if (lease != null) unawaited(_closeLease(origin, token, lease));
  }
}

class NearbyDialog extends StatefulWidget {
  const NearbyDialog({super.key});
  @override
  State<NearbyDialog> createState() => _NearbyDialogState();
}

class _NearbyDialogState extends State<NearbyDialog> {
  final controller = NearbyController.instance;
  bool? member;
  bool agreed = false;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      await Api.autoConnect();
      final account = await Api.get('/auth/me');
      if (mounted) setState(() => member = account['kind'] == 'member');
    } catch (_) {
      if (mounted) setState(() => member = false);
    }
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller,
    builder: (context, child) => AlertDialog(
      title: const Text('근처 수집가 알림'),
      content: SizedBox(
        width: 340,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                '서로 위치 공유를 켠 사용자가 약 1km 안에 있으면 앱 안에서 알려드려요. 이름·정확한 위치·거리는 공개하지 않아요.',
              ),
              const SizedBox(height: 12),
              const Text(
                '공유는 앱 화면을 보고 있는 동안 최대 15분만 유지돼요. 다른 앱이나 탭으로 이동하면 꺼지고, 알림은 10분에 한 번만 표시돼요. 앱을 닫은 동안의 푸시 알림은 지원하지 않아요.',
                style: TextStyle(fontSize: 13, height: 1.6),
              ),
              const SizedBox(height: 12),
              const Text(
                '위치는 기기에서 약 100m 단위로 줄여 서버에 보내며, DB나 이동 기록으로 저장하지 않아요. 끄기 요청이 전달되지 않으면 최대 90초간 근처 사용자로 표시될 수 있어요.',
                style: TextStyle(fontSize: 12, height: 1.6),
              ),
              const SizedBox(height: 16),
              Text(
                controller.message,
                style: const TextStyle(fontWeight: FontWeight.w600),
              ),
              if (member == null) const LinearProgressIndicator(),
              if (member == false)
                const Padding(
                  padding: EdgeInsets.only(top: 16),
                  child: Text(
                    '상단 로그인에서 구글·카카오로 로그인한 뒤 이용해 주세요. 로그인 연결이 준비되면 켤 수 있어요.',
                  ),
                ),
              if (member == true && !controller.active && !controller.starting)
                CheckboxListTile(
                  contentPadding: EdgeInsets.zero,
                  value: agreed,
                  onChanged: (value) => setState(() => agreed = value ?? false),
                  title: const Text(
                    '이번 15분 동안 위치 공유에 동의해요.',
                    style: TextStyle(fontSize: 14),
                  ),
                ),
            ],
          ),
        ),
      ),
      actions: [
        if (controller.active || controller.starting)
          FilledButton(
            onPressed: () {
              controller.stop();
              setState(() => agreed = false);
            },
            child: const Text('위치 공유 끄기'),
          )
        else
          FilledButton(
            onPressed: member == true && agreed
                ? () {
                    setState(() => agreed = false);
                    controller.start();
                  }
                : null,
            child: const Text('위치 공유 켜기'),
          ),
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('닫기'),
        ),
      ],
    ),
  );
}
