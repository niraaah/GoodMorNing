import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';
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
  List<RadarGroup> groups = [];
  DateTime? updatedAt;
  int remainingSeconds = 0;
  int get count => groups.fold(0, (sum, group) => sum + group.count);
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
      final result = await _request(origin, token, 'start', {
        'consent': true,
        'radar': true,
      });
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
      groups = (result['clusters'] as List? ?? [])
          .map((value) => RadarGroup.fromJson(Map<String, dynamic>.from(value)))
          .toList();
      updatedAt = DateTime.now();
      remainingSeconds = result['remaining_seconds'] as int;
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
    groups = [];
    updatedAt = null;
    remainingSeconds = 0;
    message = reason;
    notifyListeners();
    if (lease != null) unawaited(_closeLease(origin, token, lease));
  }
}

class RadarGroup {
  final int band, count;
  final int? direction;
  const RadarGroup(this.band, this.direction, this.count);
  factory RadarGroup.fromJson(Map<String, dynamic> value) => RadarGroup(
    value['band'] as int,
    value['direction'] as int?,
    value['count'] as int,
  );
  String get key => '$band-$direction';
  String get distance => const ['약 300m 이내', '약 300~600m', '약 600m~1km'][band];
  String get bearing => direction == null
      ? '방향 확인 어려움'
      : '${const ['북', '북동', '동', '남동', '남', '남서', '서', '북서'][direction!]}쪽 부근';
  String get label => '$distance · $bearing · $count명';
}

class NearbyPage extends StatefulWidget {
  const NearbyPage({super.key});
  @override
  State<NearbyPage> createState() => _NearbyPageState();
}

class _NearbyPageState extends State<NearbyPage> {
  final controller = NearbyController.instance;
  bool? member;
  bool agreed = false;
  String? selected, error;
  Uint8List? photo;
  static const ink = Color(0xff294653), muted = Color(0xff6d8795);
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      await Api.autoConnect();
      final account = await Api.get('/auth/me');
      Uint8List? bytes;
      if (account['has_avatar'] == true) {
        try {
          final response = await http
              .get(Api.uri('/auth/avatar'), headers: Api.headers)
              .timeout(const Duration(seconds: 12));
          if (response.statusCode == 200) bytes = response.bodyBytes;
        } catch (_) {
          /* The default avatar is always available. */
        }
      }
      if (mounted)
        setState(() {
          member =
              account['kind'] == 'member' && account['profile_ready'] == true;
          photo = bytes;
          error = null;
        });
    } catch (_) {
      if (mounted) setState(() => error = '서버에 연결하지 못했어요. 연결 후 다시 시도해 주세요.');
    }
  }

  void select(RadarGroup group) => setState(() => selected = group.key);

  void listGroups() {
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheet) => SafeArea(
        child: SizedBox(
          height: MediaQuery.sizeOf(sheet).height * .55,
          child: ListenableBuilder(
            listenable: controller,
            builder: (_, _) => Column(
              children: [
                const Padding(
                  padding: EdgeInsets.all(16),
                  child: Text(
                    '근처 수집가 목록',
                    style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold),
                  ),
                ),
                if (controller.groups.isEmpty)
                  const Padding(
                    padding: EdgeInsets.all(24),
                    child: Text('현재 표시할 수집가가 없어요.'),
                  ),
                Expanded(
                  child: ListView(
                    children: [
                      for (final group in controller.groups)
                        ListTile(
                          leading: const Icon(Icons.people_outline),
                          title: Text('${group.count}명 · ${group.distance}'),
                          subtitle: Text(group.bearing),
                          onTap: () {
                            select(group);
                            Navigator.pop(sheet);
                          },
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller,
    builder: (_, _) {
      final active = controller.active;
      final chosen = controller.groups
          .where((group) => group.key == selected)
          .firstOrNull;
      return Scaffold(
        backgroundColor: const Color(0xffeef7fc),
        appBar: AppBar(
          title: const Text('근처 수집가'),
          backgroundColor: const Color(0xffeef7fc),
          actions: [
            IconButton(
              tooltip: '거리·방향 공유 안내',
              icon: const Icon(Icons.info_outline),
              onPressed: () => showDialog<void>(
                context: context,
                builder: (ctx) => AlertDialog(
                  title: const Text('서로 켠 동안만 보여요'),
                  content: const SingleChildScrollView(
                    child: Text(
                      '이번 15분 동안 서로 공유 중인 사용자에게 대략적인 거리 구간·8방향·인원수가 표시돼요. 이름·사진·좌표·정확한 거리는 공개하지 않아요. 같은 구간의 수집가는 묶어서 보여요.\n\n화면 위는 북쪽이며 휴대폰이 향한 방향과는 달라요. GPS 오차나 가까운 거리 때문에 방향을 알기 어려우면 거리만 보여요.\n\n위치는 약 100m 단위로 줄여 서버 메모리에서만 처리해요. 다른 앱·탭 이동, 로그아웃, 15분 경과 시 꺼져요. 끄기 요청이 전달되지 않으면 마지막 갱신 뒤 90초까지 표시될 수 있어요. DB나 이동 이력에는 저장하지 않아요.',
                    ),
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: const Text('알겠어요'),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
        body: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    children: [
                      Icon(
                        active ? Icons.radar : Icons.location_off_outlined,
                        color: active ? const Color(0xff4d8879) : muted,
                        size: 18,
                      ),
                      const SizedBox(width: 8),
                      Text(
                        active ? '위치 공유 중' : '위치 공유 꺼짐',
                        style: const TextStyle(color: muted),
                      ),
                      const Spacer(),
                      const Icon(Icons.north, size: 15, color: muted),
                      const SizedBox(width: 4),
                      const Text(
                        '위쪽은 북쪽',
                        style: TextStyle(color: muted, fontSize: 12),
                      ),
                    ],
                  ),
                  const SizedBox(height: 20),
                  Text(
                    active && controller.updatedAt != null
                        ? '우리 근처에 ${controller.count}명'
                        : '우리 근처, 누가 있을까요?',
                    style: const TextStyle(
                      fontSize: 25,
                      fontWeight: FontWeight.bold,
                      color: ink,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    active
                        ? controller.message
                        : '서로 공유를 켠 수집가의 거리와 방향을 가볍게 살펴봐요.',
                    style: const TextStyle(color: muted, height: 1.5),
                  ),
                  const SizedBox(height: 16),
                  RadarChart(
                    groups: controller.groups,
                    photo: photo,
                    selected: selected,
                    onSelect: select,
                    active: active,
                  ),
                  const Center(
                    child: Text(
                      '안쪽부터 약 300m · 600m · 1km',
                      style: TextStyle(fontSize: 12, color: muted),
                    ),
                  ),
                  const SizedBox(height: 16),
                  if (controller.groups.any(
                    (group) => group.direction == null,
                  )) ...[
                    const Text(
                      '방향을 알기 어려운 수집가',
                      style: TextStyle(color: ink, fontWeight: FontWeight.w600),
                    ),
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: [
                        for (final group in controller.groups.where(
                          (group) => group.direction == null,
                        ))
                          ActionChip(
                            avatar: const Icon(Icons.people_outline, size: 18),
                            label: Text('${group.distance} · ${group.count}명'),
                            onPressed: () => select(group),
                          ),
                      ],
                    ),
                    const Text(
                      '위치 오차가 크거나 너무 가까우면 거리만 표시해요.',
                      style: TextStyle(color: muted, fontSize: 12),
                    ),
                    const SizedBox(height: 12),
                  ],
                  Container(
                    padding: const EdgeInsets.all(18),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Row(
                      children: [
                        Icon(
                          chosen == null
                              ? Icons.explore_outlined
                              : Icons.people_outline,
                          color: ink,
                          size: 26,
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                chosen == null
                                    ? (active && controller.count == 0
                                          ? '공유 중인 수집가를 기다리고 있어요'
                                          : active
                                          ? '아이콘을 눌러 살펴보세요'
                                          : '나를 중심으로 가까운 수집가 찾기')
                                    : '익명 수집가 ${chosen.count}명',
                                style: const TextStyle(
                                  fontWeight: FontWeight.w600,
                                  color: ink,
                                ),
                              ),
                              const SizedBox(height: 5),
                              Text(
                                chosen == null
                                    ? '이름이나 사진, 정확한 위치는 공개하지 않아요.'
                                    : '${chosen.distance} · ${chosen.bearing}',
                                style: const TextStyle(
                                  color: muted,
                                  fontSize: 13,
                                  height: 1.5,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (active) ...[
                    Align(
                      alignment: Alignment.centerRight,
                      child: TextButton.icon(
                        onPressed: listGroups,
                        icon: const Icon(Icons.list_alt, size: 18),
                        label: const Text('목록으로 보기'),
                      ),
                    ),
                    Text(
                      controller.updatedAt == null
                          ? '위치를 확인하고 있어요…'
                          : '30초마다 갱신 · 공유 약 ${(controller.remainingSeconds / 60).ceil()}분 남음',
                      style: const TextStyle(fontSize: 12, color: muted),
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      '대략적인 구간이에요. 실제 거리·방향은 GPS 오차에 따라 달라질 수 있어요.',
                      style: TextStyle(fontSize: 12, color: muted, height: 1.5),
                    ),
                  ],
                  if (!active && !controller.starting) ...[
                    const SizedBox(height: 18),
                    if (member == null && error == null)
                      const LinearProgressIndicator(),
                    if (member == false)
                      const Text(
                        '로그인과 첫 프로필 설정을 마치면 사용할 수 있어요.',
                        style: TextStyle(color: muted),
                      ),
                    if (member == true) ...[
                      const Text(
                        '이번 15분 동안 내 대략적인 거리·방향도 공유 중인 사람들에게 표시돼요. 앱을 벗어나면 꺼지고 위치는 DB에 저장하지 않아요.',
                        style: TextStyle(
                          fontSize: 13,
                          height: 1.6,
                          color: muted,
                        ),
                      ),
                      CheckboxListTile(
                        contentPadding: EdgeInsets.zero,
                        value: agreed,
                        onChanged: (value) =>
                            setState(() => agreed = value ?? false),
                        title: const Text(
                          '이번 위치·거리·방향 공유에 동의해요.',
                          style: TextStyle(fontSize: 14),
                        ),
                      ),
                    ],
                    Text(
                      controller.message,
                      style: const TextStyle(fontSize: 12, color: muted),
                    ),
                  ],
                  if (controller.starting)
                    const Padding(
                      padding: EdgeInsets.all(16),
                      child: LinearProgressIndicator(),
                    ),
                  if (error != null) ...[
                    Text(error!, style: const TextStyle(color: Colors.red)),
                    TextButton(onPressed: load, child: const Text('연결 다시 확인')),
                  ],
                ],
              ),
            ),
          ),
        ),
        bottomNavigationBar: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(20, 12, 20, 12),
            child: Center(
              heightFactor: 1,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: SizedBox(
                  width: double.infinity,
                  child: FilledButton.icon(
                    onPressed: active || controller.starting
                        ? () {
                            controller.stop();
                            setState(() {
                              agreed = false;
                              selected = null;
                            });
                          }
                        : member == false
                        ? () => Navigator.pop(context, true)
                        : member == true && agreed
                        ? () {
                            setState(() => agreed = false);
                            controller.start();
                          }
                        : null,
                    icon: Icon(
                      active || controller.starting
                          ? Icons.location_off_outlined
                          : member == false
                          ? Icons.login
                          : Icons.radar,
                    ),
                    label: Text(
                      active || controller.starting
                          ? '위치 공유 끄기'
                          : member == false
                          ? '로그인 / 프로필 설정'
                          : '거리·방향 공유 켜기',
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    },
  );
}

class RadarChart extends StatelessWidget {
  final List<RadarGroup> groups;
  final Uint8List? photo;
  final String? selected;
  final bool active;
  final ValueChanged<RadarGroup> onSelect;
  const RadarChart({
    super.key,
    required this.groups,
    required this.photo,
    required this.selected,
    required this.onSelect,
    required this.active,
  });
  @override
  Widget build(BuildContext context) => AspectRatio(
    aspectRatio: 1,
    child: LayoutBuilder(
      builder: (context, limits) {
        final center = limits.maxWidth / 2, radius = center - 22;
        return Stack(
          clipBehavior: Clip.none,
          children: [
            Positioned.fill(child: CustomPaint(painter: RadarRings(active))),
            const Positioned(
              top: 0,
              left: 0,
              right: 0,
              child: Center(
                child: Text(
                  '북',
                  style: TextStyle(color: Color(0xff6d8795), fontSize: 12),
                ),
              ),
            ),
            const Positioned(
              bottom: 0,
              left: 0,
              right: 0,
              child: Center(
                child: Text(
                  '남',
                  style: TextStyle(color: Color(0xff6d8795), fontSize: 12),
                ),
              ),
            ),
            Positioned(
              left: 0,
              top: center - 8,
              child: const Text(
                '서',
                style: TextStyle(color: Color(0xff6d8795), fontSize: 12),
              ),
            ),
            Positioned(
              right: 0,
              top: center - 8,
              child: const Text(
                '동',
                style: TextStyle(color: Color(0xff6d8795), fontSize: 12),
              ),
            ),
            Positioned(
              left: center - 25,
              top: center - 25,
              width: 50,
              height: 50,
              child: Semantics(
                label: '나, 거리와 방향의 기준',
                child: CircleAvatar(
                  backgroundColor: const Color(0xff294653),
                  child: photo == null
                      ? const Icon(Icons.person, color: Colors.white, size: 30)
                      : ClipOval(
                          child: Image.memory(
                            photo!,
                            width: 50,
                            height: 50,
                            fit: BoxFit.cover,
                            errorBuilder: (_, _, _) =>
                                const Icon(Icons.person, color: Colors.white),
                          ),
                        ),
                ),
              ),
            ),
            Positioned(
              left: center - 10,
              top: center + 11,
              width: 20,
              child: Container(
                decoration: BoxDecoration(
                  color: const Color(0xff294653),
                  borderRadius: BorderRadius.circular(6),
                ),
                child: const Center(
                  child: Text(
                    '나',
                    style: TextStyle(fontSize: 10, color: Colors.white),
                  ),
                ),
              ),
            ),
            for (final group in groups.where(
              (value) => value.direction != null,
            ))
              Positioned(
                left:
                    center +
                    math.sin(group.direction! * math.pi / 4) *
                        radius *
                        const [.36, .63, .90][group.band] -
                    18,
                top:
                    center -
                    math.cos(group.direction! * math.pi / 4) *
                        radius *
                        const [.36, .63, .90][group.band] -
                    18,
                width: 36,
                height: 36,
                child: Tooltip(
                  message: group.label,
                  child: Semantics(
                    button: true,
                    label: group.label,
                    child: InkWell(
                      onTap: () => onSelect(group),
                      borderRadius: BorderRadius.circular(18),
                      child: Container(
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: const [
                            Color(0xffd0e7e4),
                            Color(0xffd9e8f5),
                            Color(0xfff0dfd4),
                          ][group.band],
                          border: Border.all(
                            color: selected == group.key
                                ? const Color(0xff294653)
                                : Colors.white,
                            width: selected == group.key ? 3 : 2,
                          ),
                        ),
                        child: Center(
                          child: group.count == 1
                              ? const Icon(
                                  Icons.person_outline,
                                  size: 23,
                                  color: Color(0xff294653),
                                )
                              : Text(
                                  '${group.count}',
                                  style: const TextStyle(
                                    fontWeight: FontWeight.bold,
                                    fontSize: 13,
                                    color: Color(0xff294653),
                                  ),
                                ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
          ],
        );
      },
    ),
  );
}

class RadarRings extends CustomPainter {
  final bool active;
  RadarRings(this.active);
  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2),
        radius = size.width / 2 - 22;
    final line = Paint()
      ..color = active ? const Color(0xffbfd5df) : const Color(0xffd7e5ec)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1;
    for (final fraction in [.4, .67, .94]) {
      canvas.drawCircle(center, radius * fraction, line);
    }
  }

  @override
  bool shouldRepaint(covariant RadarRings oldDelegate) =>
      active != oldDelegate.active;
}
