import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';
import 'dart:ui' as ui;
import 'package:file_picker/file_picker.dart';
import 'package:material_ui/material_ui.dart';
import 'api.dart';
import 'diary_scene.dart';
import 'reference_view.dart';
import 'photo_selection.dart';
import 'studio_dialog.dart';
import 'asset_actions.dart';
import 'goods_match_dialog.dart';
import 'account_dialog.dart';
import 'account_page.dart';
import 'nearby.dart';
import 'package:web/web.dart' as web;

const ink = Color(0xff294653),
    blue = Color(0xff659bb7),
    sky = Color(0xffeef7fc),
    line = Color(0xffd5e5ed);
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  try {
    await Api.initialize();
  } catch (_) {
    runApp(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text(
                    '브라우저 저장 정보를 정리하지 못했어요. 다른 굿모닝 탭을 모두 닫고 다시 시도해 주세요.',
                  ),
                  TextButton(
                    onPressed: () => web.window.location.reload(),
                    child: const Text('다시 시도'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
    return;
  }
  runApp(const GoodMorning());
}

class GoodMorning extends StatelessWidget {
  const GoodMorning({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
    title: '굿모닝 · 나의 작은 수집방',
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      scaffoldBackgroundColor: sky,
      fontFamily: 'Malgun Gothic',
      colorScheme: ColorScheme.fromSeed(seedColor: blue, surface: Colors.white),
      textTheme: const TextTheme(
        bodyMedium: TextStyle(color: ink),
        titleLarge: TextStyle(color: ink, fontWeight: FontWeight.w700),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: ink,
          foregroundColor: Colors.white,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 18),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
          ),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xfff6fafc),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: line),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: line),
        ),
      ),
    ),
    home: const Studio(),
  );
}

class Studio extends StatefulWidget {
  const Studio({super.key});
  @override
  State<Studio> createState() => _StudioState();
}

class _StudioState extends State<Studio> {
  List<Map<String, dynamic>> assets = [], diaries = [], jobs = [];
  List<Map<String, dynamic>> get stickerAssets =>
      assets.where((asset) => asset['kind'] == 'sticker').toList();
  Map<String, dynamic>? health;
  String? error, diaryId, selected, pendingNotebookAsset;
  int tab = Uri.base.queryParameters.containsKey('browse')
      ? 3
      : Uri.base.queryParameters.containsKey('magnets')
      ? 2
      : 0;
  bool loading = true, tilt = false, saving = false, polling = false;
  bool stickerDialogOpen = false, trashDialogOpen = false;
  bool accountDialogOpen = false, nearbyDialogOpen = false;
  int nearbyAlertSerial = 0;
  final nearby = NearbyController.instance;
  String accountLabel = '로그인';
  String search = '', saveStatus = '저장됨';
  Timer? poll, saveTimer;
  final pending = <String, String>{};
  final sceneKey = GlobalKey<DiarySceneState>();
  Map<String, dynamic>? get diary =>
      diaries.where((d) => d['id'] == diaryId).firstOrNull;
  List<Map<String, dynamic>> get placements =>
      List<Map<String, dynamic>>.from(diary?['placements'] ?? []);
  Map<String, dynamic>? get selection =>
      placements.where((p) => p['id'] == selected).firstOrNull;
  @override
  void initState() {
    super.initState();
    nearby.addListener(nearbyChanged);
    load();
    poll = Timer.periodic(const Duration(seconds: 2), (_) => pollJobs());
  }

  @override
  void dispose() {
    nearby.removeListener(nearbyChanged);
    nearby.stop();
    poll?.cancel();
    saveTimer?.cancel();
    super.dispose();
  }

  void nearbyChanged() {
    if (!mounted) return;
    setState(() {});
    if (nearby.alertSerial != nearbyAlertSerial) {
      nearbyAlertSerial = nearby.alertSerial;
      notify('근처에 굿모닝을 사용 중인 수집가가 있어요!');
    }
  }

  Future<void> showNearby() async {
    if (nearbyDialogOpen) return;
    nearbyDialogOpen = true;
    try {
      final login = await Navigator.push<bool>(
        context,
        MaterialPageRoute(builder: (_) => const NearbyPage()),
      );
      if (login == true && mounted) await showAccount();
    } finally {
      nearbyDialogOpen = false;
    }
  }

  void notify(String text) {
    if (mounted)
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(text), behavior: SnackBarBehavior.floating),
      );
  }

  Future<void> load() async {
    try {
      await Api.autoConnect();
    } catch (e) {
      if (mounted)
        setState(() {
          loading = false;
          health = null;
          error = Api.errorMessage(e);
        });
      return;
    }
    if (!Api.configured) {
      setState(() => loading = false);
      return;
    }
    try {
      var account = await Api.get('/auth/me');
      if (account['kind'] == 'member' && account['profile_ready'] != true) {
        if (!mounted) return;
        await Navigator.push(
          context,
          MaterialPageRoute(
            builder: (_) => const AccountPage(onboarding: true),
          ),
        );
        account = await Api.get('/auth/me');
      }
      final result = await Future.wait([
        Api.get('/api/assets'),
        Api.get('/api/diaries'),
        Api.get('/api/jobs'),
        Api.get('/api/health'),
        Api.get('/auth/me'),
      ]);
      if (!mounted) return;
      setState(() {
        assets = List<Map<String, dynamic>>.from(result[0]);
        diaries = List<Map<String, dynamic>>.from(result[1]);
        jobs = List<Map<String, dynamic>>.from(result[2]);
        health = Map<String, dynamic>.from(result[3]);
        accountLabel = result[4]['kind'] == 'member' ? '내 계정' : '로그인';
        diaryId ??= diaries.firstOrNull?['id'];
        loading = false;
        error = null;
      });
    } catch (e) {
      if (mounted)
        setState(() {
          loading = false;
          health = null;
          error = Api.errorMessage(e);
        });
    }
  }

  Future<void> pollJobs() async {
    if (polling || !jobs.any((j) => ['queued', 'running'].contains(j['state'])))
      return;
    polling = true;
    try {
      final fresh = List<Map<String, dynamic>>.from(await Api.get('/api/jobs'));
      final completed = fresh.any(
        (j) =>
            j['state'] == 'completed' &&
            jobs.any(
              (old) => old['id'] == j['id'] && old['state'] != 'completed',
            ),
      );
      final library = completed
          ? List<Map<String, dynamic>>.from(await Api.get('/api/assets'))
          : assets;
      if (mounted)
        setState(() {
          jobs = [
            ...jobs.where((j) => j['id'].toString().startsWith('upload-')),
            ...fresh,
          ];
          assets = library;
        });
      if (completed) notify('새 볼록 스티커가 에셋함에 도착했어요!');
    } catch (e) {
      if (mounted)
        setState(() => error = '서버 연결을 확인해 주세요. 만들던 작업은 서버에 남아 있어요.');
    } finally {
      polling = false;
    }
  }

  void changed() {
    if (diary == null) return;
    pending[diary!['id']] = jsonEncode(diary);
    saveStatus = '저장 중…';
    saveTimer?.cancel();
    saveTimer = Timer(const Duration(milliseconds: 450), flush);
  }

  Future<void> flush() async {
    if (saving || pending.isEmpty) return;
    saving = true;
    while (pending.isNotEmpty) {
      final entry = pending.entries.first;
      try {
        await Api.save(Map<String, dynamic>.from(jsonDecode(entry.value)));
        if (pending[entry.key] == entry.value) pending.remove(entry.key);
      } catch (e) {
        if (mounted) setState(() => saveStatus = '저장 실패 · 다시 시도');
        saving = false;
        return;
      }
    }
    saving = false;
    if (mounted) setState(() => saveStatus = '모든 변경 저장됨');
  }

  void addAsset(Map<String, dynamic> asset) {
    setState(() {
      pendingNotebookAsset = asset['id'] as String;
      tab = 2;
    });
  }

  void patch(String field, double value) {
    if (selection == null) return;
    setState(() {
      selection![field] = value;
      changed();
    });
  }

  void removeSelection() {
    setState(() {
      diary!['placements'] = placements
          .where((p) => p['id'] != selected)
          .toList();
      selected = null;
      changed();
    });
  }

  Future<void> newDiary() async {
    final id = DateTime.now().microsecondsSinceEpoch.toString();
    final value = <String, dynamic>{
      'id': id,
      'title': '나의 새로운 하루',
      'date': DateTime.now().toIso8601String().substring(0, 10),
      'note': '',
      'paper': '#fff9eb',
      'placements': <Map<String, dynamic>>[],
    };
    try {
      await Api.save(value);
      if (mounted)
        setState(() {
          diaries.insert(0, value);
          diaryId = id;
          selected = null;
          tab = 2;
        });
    } catch (e) {
      notify(e.toString());
    }
  }

  Future<void> editDiary() async {
    if (diary == null) return;
    final title = TextEditingController(text: diary!['title']),
        note = TextEditingController(text: diary!['note']);
    final accepted = await showStudioDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('오늘의 기록'),
        content: SizedBox(
          width: 420,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(
                controller: title,
                maxLength: 60,
                decoration: const InputDecoration(labelText: '다이어리 제목'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: note,
                maxLines: 5,
                maxLength: 1000,
                decoration: const InputDecoration(labelText: '남기고 싶은 이야기'),
              ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('기록하기'),
          ),
        ],
      ),
    );
    if (accepted == true && title.text.trim().isNotEmpty && mounted)
      setState(() {
        diary!['title'] = title.text.trim();
        diary!['note'] = note.text;
        changed();
      });
    // Dialog fields still exist during the dismissal animation.
    await Future<void>.delayed(const Duration(milliseconds: 350));
    title.dispose();
    note.dispose();
  }

  Future<void> uploadPhoto() async {
    try {
      final files = await FilePicker.platform.pickFiles(
        type: FileType.image,
        withData: true,
      );
      if (files == null || files.files.single.bytes == null) return;
      final f = files.files.single;
      final asset = Map<String, dynamic>.from(
        await Api.upload('/api/photos', f.bytes!, f.name, {'name': '나의 사진'}),
      );
      if (!mounted) return;
      addAsset(asset);
    } catch (e) {
      notify(e.toString());
    }
  }

  Future<void> createSticker() async {
    if (stickerDialogOpen) return;
    stickerDialogOpen = true;
    Map<String, dynamic>? draft;
    try {
      while (mounted) {
        draft = await showStudioDialog<Map<String, dynamic>>(
          context: context,
          builder: (_) => const StickerDialog(),
        );
        if (draft == null || !mounted) return;
        final choice = await showStudioDialog<Map<String, String>>(
          context: context,
          builder: (_) => GoodsMatchDialog(draft: draft!),
        );
        if (choice == null || !mounted) return;
        if (choice['retry_photo'] == 'true') continue;
        (draft['fields'] as Map<String, String>).addAll(choice);
        break;
      }
    } finally {
      stickerDialogOpen = false;
    }
    if (draft == null || !mounted) return;
    final uploadId = 'upload-${DateTime.now().microsecondsSinceEpoch}';
    final stickerName = draft['name'] as String;
    setState(() {
      jobs.insert(0, {
        'id': uploadId,
        'name': stickerName,
        'state': 'uploading',
        'progress': 0,
        'message': '사진을 보내고 있어요…',
      });
      tab = 1;
    });
    try {
      final result = Map<String, dynamic>.from(
        await Api.upload(
          '/api/stickers',
          draft['photo'] as Uint8List,
          draft['filename'] as String,
          Map<String, String>.from(draft['fields'] as Map),
        ),
      );
      if (!mounted) return;
      setState(() {
        jobs.removeWhere((j) => j['id'] == uploadId);
        jobs.insert(0, {
          ...result,
          'name': stickerName,
          'progress': 0,
          'message': '누끼를 준비하고 있어요',
        });
      });
      pollJobs();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        jobs.removeWhere((j) => j['id'] == uploadId);
        jobs.insert(0, {
          'id': uploadId,
          'name': stickerName,
          'state': 'failed',
          'message': '사진 전송 실패: ${Api.errorMessage(e)}',
        });
      });
      notify('사진을 보내지 못했어요. 에셋 화면에서 오류를 확인해 주세요.');
    }
  }

  Widget thumbnail(
    Map<String, dynamic> asset, {
    double? width,
    double? height,
  }) => SizedBox(
    width: width,
    height: height,
    child: FutureBuilder<Uint8List>(
      future: Api.image(asset['thumbnail']),
      builder: (_, snapshot) => snapshot.hasData
          ? Image.memory(
              snapshot.data!,
              width: width,
              height: height,
              fit: BoxFit.contain,
              errorBuilder: (_, e, s) =>
                  const Icon(Icons.broken_image_outlined, color: blue),
            )
          : snapshot.hasError
          ? const Icon(Icons.broken_image_outlined, color: blue)
          : const Center(child: CircularProgressIndicator(strokeWidth: 2)),
    ),
  );
  Widget pill(String text, {Color? color}) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
    decoration: BoxDecoration(
      color: color ?? const Color(0xffe7f1f6),
      borderRadius: BorderRadius.circular(20),
    ),
    child: Text(
      text,
      style: const TextStyle(
        fontSize: 11,
        fontWeight: FontWeight.w600,
        color: ink,
      ),
    ),
  );
  Future<void> reconnect() async {
    if (loading) return;
    nearby.stop();
    Api.resetConnection();
    setState(() {
      loading = true;
      health = null;
      error = null;
    });
    await load();
  }

  void navigate(int value) => setState(() => tab = value);

  Future<void> showAccount() async {
    if (accountDialogOpen) return;
    accountDialogOpen = true;
    try {
      final account = await Api.get('/auth/me');
      if (!mounted) return;
      if (account['kind'] == 'member') {
        await Navigator.push(
          context,
          MaterialPageRoute(builder: (_) => const AccountPage()),
        );
        await load();
      } else {
        await showStudioDialog<void>(
          context: context,
          builder: (_) => const AccountDialog(),
        );
      }
    } catch (e) {
      notify(e.toString().replaceFirst('Exception: ', ''));
    } finally {
      accountDialogOpen = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (tab == 0 || tab == 2 || tab == 3) {
      return Scaffold(
        body: ReferenceView(
          tab: tab,
          onNavigate: navigate,
          onAccount: showAccount,
          onNearby: showNearby,
          nearbyActive: nearby.active,
          accountLabel: accountLabel,
          connectionReady: health != null,
          connectionError: error,
          diaryId: diaryId,
          pendingAsset: pendingNotebookAsset,
          onAssetAdded: (id) {
            if (pendingNotebookAsset == id)
              setState(() => pendingNotebookAsset = null);
          },
          onError: notify,
        ),
      );
    }
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 568),
            child: Column(
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                  child: SizedBox(
                    height: 60,
                    child: Row(
                      children: [
                        GestureDetector(
                          onTap: () => navigate(0),
                          child: Image.asset(
                            'assets/brand-banner.jpg',
                            width:
                                MediaQuery.sizeOf(
                                  context,
                                ).width.clamp(314, 454) *
                                .43,
                            fit: BoxFit.contain,
                          ),
                        ),
                        const Spacer(),
                        IconButton(
                          onPressed: showNearby,
                          tooltip: nearby.active
                              ? '위치 공유 중 · 끄기/설정'
                              : '근처 수집가 알림',
                          constraints: const BoxConstraints(
                            minWidth: 32,
                            minHeight: 40,
                          ),
                          padding: const EdgeInsets.all(4),
                          icon: Icon(
                            nearby.active ? Icons.map : Icons.map_outlined,
                            size: 20,
                            color: nearby.active
                                ? const Color(0xff168264)
                                : ink,
                          ),
                        ),
                        TextButton(
                          onPressed: showAccount,
                          child: Text(
                            accountLabel,
                            style: const TextStyle(fontSize: 12),
                          ),
                        ),
                        TextButton(
                          onPressed: loading || health != null
                              ? null
                              : reconnect,
                          child: Text(
                            health == null ? '다시 연결' : '연결됨',
                            style: const TextStyle(fontSize: 12),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                Expanded(
                  child: loading
                      ? const Center(child: CircularProgressIndicator())
                      : (!Api.configured || error != null && assets.isEmpty)
                      ? Center(
                          child: Padding(
                            padding: const EdgeInsets.all(28),
                            child: Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                const Text(
                                  '수집방을 불러오지 못했어요',
                                  style: TextStyle(
                                    fontSize: 20,
                                    fontWeight: FontWeight.bold,
                                  ),
                                ),
                                const SizedBox(height: 12),
                                Text(
                                  error == null
                                      ? '잠시 후 다시 시도해 주세요.'
                                      : '잠시 연결이 끊겼어요. 저장된 자료는 그대로 보관돼요.',
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(
                                    fontSize: 13,
                                    height: 1.7,
                                  ),
                                ),
                                const SizedBox(height: 20),
                                FilledButton(
                                  onPressed: reconnect,
                                  child: const Text('다시 시도'),
                                ),
                              ],
                            ),
                          ),
                        )
                      : tab == 1
                      ? library()
                      : editor(false),
                ),
                SizedBox(
                  height: 71,
                  child: ReferenceView(
                    navigationOnly: true,
                    tab: tab,
                    onNavigate: navigate,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget heading(
    String overline,
    String title,
    String subtitle, {
    Widget? action,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 24),
    child: Row(
      crossAxisAlignment: CrossAxisAlignment.center,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                overline,
                style: const TextStyle(
                  fontSize: 10,
                  letterSpacing: 2,
                  color: blue,
                  fontWeight: FontWeight.bold,
                ),
              ),
              const SizedBox(height: 9),
              Text(
                title,
                style: const TextStyle(
                  fontSize: 27,
                  fontWeight: FontWeight.w700,
                  color: ink,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                subtitle,
                style: const TextStyle(
                  fontSize: 12,
                  color: Color(0xff78909c),
                  height: 1.6,
                ),
              ),
            ],
          ),
        ),
        ?action,
      ],
    ),
  );
  Widget assetCard(Map<String, dynamic> asset, {bool compact = false}) =>
      InkWell(
        onTap: () => showAsset(asset),
        borderRadius: BorderRadius.circular(8),
        child: Container(
          padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(
            color: const Color(0xffe6f2fa),
            border: Border.all(color: const Color(0xffc9dfe9)),
            borderRadius: BorderRadius.circular(8),
          ),
          child: Column(
            children: [
              Expanded(child: thumbnail(asset)),
              const SizedBox(height: 8),
              Text(
                asset['name'],
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
              if (!compact)
                Text(
                  asset['kind'] == 'photo'
                      ? '폴라로이드'
                      : asset['engine'] == 'sam3d-sample'
                      ? '기본 스티커'
                      : '내가 만든 스티커',
                  style: const TextStyle(fontSize: 9, color: blue),
                ),
            ],
          ),
        ),
      );
  Future<void> showAsset(Map<String, dynamic> asset) async {
    final action = await showStudioDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(asset['name']),
        content: SizedBox(
          width: 300,
          height: 340,
          child: Column(
            children: [
              Expanded(child: thumbnail(asset)),
              if (asset['metadata']?['goods'] is Map) ...[
                const SizedBox(height: 10),
                Text(
                  asset['metadata']['goods']['title'],
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 12),
                ),
                TextButton.icon(
                  onPressed: () => web.window.open(
                    asset['metadata']['goods']['url'],
                    '_blank',
                    'noopener,noreferrer',
                  ),
                  icon: const Icon(Icons.open_in_new, size: 16),
                  label: const Text('연결한 굿즈 보기'),
                ),
                if (asset['metadata']['goods']['affiliate'] == true)
                  const Text(
                    '쿠팡 파트너스 링크를 통해 구매하면 운영자가 일정액의 수수료를 제공받을 수 있습니다.',
                    style: TextStyle(fontSize: 10, height: 1.4),
                  ),
              ],
            ],
          ),
        ),
        actions: [
          if (asset['engine'] != 'sam3d-sample')
            TextButton.icon(
              onPressed: () => Navigator.pop(ctx, 'delete'),
              icon: const Icon(Icons.delete_outline, color: Color(0xffa9453c)),
              label: const Text(
                '삭제',
                style: TextStyle(color: Color(0xffa9453c)),
              ),
            ),
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Tooltip(
              message: '닫기',
              child: Icon(Icons.close, semanticLabel: '닫기'),
            ),
          ),
          FilledButton.icon(
            onPressed: () {
              Navigator.pop(ctx);
              addAsset(asset);
            },
            icon: const Icon(Icons.add, size: 17),
            label: const Text('다이어리에 붙이기'),
          ),
        ],
      ),
    );
    if (action == 'delete' &&
        mounted &&
        await confirmAssetDeletion(context, asset)) {
      if (!mounted) return;
      setState(() => assets.removeWhere((a) => a['id'] == asset['id']));
      notify('휴지통으로 옮겼어요. 잘못 삭제했다면 복구할 수 있어요.');
    }
  }

  Future<void> openTrash() async {
    if (trashDialogOpen) return;
    trashDialogOpen = true;
    try {
      await showStudioDialog(
        context: context,
        builder: (_) => const AssetTrashDialog(),
      );
      final fresh = List<Map<String, dynamic>>.from(
        await Api.get('/api/assets'),
      );
      if (mounted) setState(() => assets = fresh);
    } catch (e) {
      notify(e.toString());
    } finally {
      trashDialogOpen = false;
    }
  }

  Widget library() {
    final filtered = stickerAssets
        .where((a) => a['name'].toString().contains(search))
        .toList();
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
      children: [
        Padding(
          padding: const EdgeInsets.only(bottom: 16),
          child: Row(
            children: [
              const Text(
                '내 에셋',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
              ),
              const Spacer(),
              TextButton.icon(
                onPressed: openTrash,
                icon: const Icon(Icons.delete_outline, size: 18),
                label: const Text('휴지통'),
              ),
            ],
          ),
        ),
        Row(
          children: [
            Expanded(
              child: TextField(
                onChanged: (s) => setState(() => search = s),
                decoration: const InputDecoration(
                  hintText: '내 에셋 찾기',
                  prefixIcon: Icon(Icons.search, size: 20),
                ),
              ),
            ),
            const SizedBox(width: 12),
            FilledButton.icon(
              onPressed: createSticker,
              icon: const Icon(Icons.add, size: 18),
              label: const Text('모으기'),
            ),
          ],
        ),
        if (jobs.isNotEmpty) ...[
          const SizedBox(height: 20),
          ...jobs
              .where((j) => j['state'] != 'completed')
              .take(4)
              .map(
                (j) => Container(
                  margin: const EdgeInsets.only(bottom: 10),
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    border: Border.all(color: line),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        j['name'] ?? '새 스티커',
                        style: const TextStyle(fontWeight: FontWeight.bold),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        j['message'] ?? '',
                        style: TextStyle(
                          fontSize: 12,
                          color: j['state'] == 'failed' ? Colors.red : blue,
                        ),
                      ),
                      if (j['state'] != 'failed') ...[
                        const SizedBox(height: 10),
                        LinearProgressIndicator(
                          value: j['state'] == 'uploading'
                              ? null
                              : ((j['progress'] ?? 0) as num) / 100,
                          backgroundColor: sky,
                          color: blue,
                        ),
                      ],
                    ],
                  ),
                ),
              ),
        ],
        const SizedBox(height: 22),
        Text(
          '${filtered.length}개의 소중한 취향',
          style: const TextStyle(fontSize: 12, color: blue),
        ),
        const SizedBox(height: 12),
        if (filtered.isEmpty)
          const Padding(
            padding: EdgeInsets.all(40),
            child: Center(child: Text('아직 모은 에셋이 없어요. 사진으로 스티커를 만들어 보세요.')),
          ),
        GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: 3,
            childAspectRatio: .86,
            crossAxisSpacing: 8,
            mainAxisSpacing: 8,
          ),
          itemCount: filtered.length,
          itemBuilder: (_, i) => assetCard(filtered[i]),
        ),
      ],
    );
  }

  Widget editor(bool wide) {
    if (diary == null)
      return Center(
        child: FilledButton(
          onPressed: newDiary,
          child: const Text('첫 다이어리 만들기'),
        ),
      );
    final canvas = ClipRRect(
      borderRadius: BorderRadius.circular(20),
      child: DiaryScene(
        key: sceneKey,
        diary: diary!,
        assets: assets,
        tilt: tilt,
        selected: selected,
        onSelect: (id) {
          if (selected != id) setState(() => selected = id);
        },
        onError: (message) => notify(message),
        onChange: (list) => setState(() {
          diary!['placements'] = list
              .map((p) => Map<String, dynamic>.from(p))
              .toList();
          changed();
        }),
      ),
    );
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(18, 8, 22, 12),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      diary!['title'],
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    TextButton.icon(
                      onPressed: flush,
                      icon: Icon(
                        saveStatus.contains('실패')
                            ? Icons.cloud_off_outlined
                            : Icons.cloud_done_outlined,
                        size: 14,
                      ),
                      label: Text(
                        saveStatus,
                        style: const TextStyle(fontSize: 10),
                      ),
                    ),
                  ],
                ),
              ),
              IconButton(
                tooltip: '제목과 글 편집',
                onPressed: editDiary,
                icon: const Icon(Icons.edit_note),
              ),
              IconButton(
                tooltip: '이미지로 저장',
                onPressed: () => sceneKey.currentState?.exportImage(),
                icon: const Icon(Icons.file_download_outlined),
              ),
            ],
          ),
        ),
        Expanded(
          child: wide
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Expanded(
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(8, 0, 16, 18),
                        child: canvas,
                      ),
                    ),
                    SizedBox(width: 260, child: tools()),
                  ],
                )
              : ListView(
                  children: [
                    SizedBox(
                      height:
                          MediaQuery.sizeOf(context).width.clamp(280, 536) *
                          1.15,
                      child: canvas,
                    ),
                    tools(),
                  ],
                ),
        ),
      ],
    );
  }

  Widget tools() => Container(
    margin: const EdgeInsets.only(right: 18, bottom: 18),
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      color: Colors.white,
      border: Border.all(color: line),
      borderRadius: BorderRadius.circular(20),
    ),
    child: SingleChildScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '다이어리 꾸미기',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 15),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: uploadPhoto,
              icon: const Icon(Icons.add_photo_alternate_outlined, size: 18),
              label: const Text('폴라로이드 사진 추가', style: TextStyle(fontSize: 12)),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              const Text('입체로 보기', style: TextStyle(fontSize: 12)),
              const Spacer(),
              Switch(value: tilt, onChanged: (v) => setState(() => tilt = v)),
            ],
          ),
          const SizedBox(height: 10),
          const Text(
            '종이 색',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 10),
          Wrap(
            spacing: 9,
            children: [
              for (final color in [
                '#fff9eb',
                '#f5e9ed',
                '#eaf4ef',
                '#eef5ff',
                '#ffffff',
              ])
                InkWell(
                  onTap: () => setState(() {
                    diary!['paper'] = color;
                    changed();
                  }),
                  child: Container(
                    width: 30,
                    height: 30,
                    decoration: BoxDecoration(
                      color: Color(
                        int.parse(color.replaceFirst('#', 'ff'), radix: 16),
                      ),
                      shape: BoxShape.circle,
                      border: Border.all(
                        color: diary!['paper'] == color ? blue : line,
                        width: 2,
                      ),
                    ),
                  ),
                ),
            ],
          ),
          const Divider(height: 32, color: line),
          if (selection != null) ...[
            const Text(
              '선택한 스티커',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 8),
            Text(
              '크기  ${((selection!['size'] as num) * 100).round()}%',
              style: const TextStyle(fontSize: 11, color: blue),
            ),
            Slider(
              min: .06,
              max: .85,
              value: (selection!['size'] as num).toDouble().clamp(.06, .85),
              onChanged: (v) => patch('size', v),
            ),
            Text(
              '회전  ${(selection!['rotation'] as num).round()}°',
              style: const TextStyle(fontSize: 11, color: blue),
            ),
            Slider(
              min: -180,
              max: 180,
              value: (selection!['rotation'] as num).toDouble().clamp(
                -180,
                180,
              ),
              onChanged: (v) => patch('rotation', v),
            ),
            Row(
              children: [
                TextButton.icon(
                  onPressed: () {
                    setState(() {
                      final p = selection!;
                      diary!['placements'] = [
                        ...placements.where((x) => x['id'] != selected),
                        p,
                      ];
                      changed();
                    });
                  },
                  icon: const Icon(Icons.flip_to_front, size: 15),
                  label: const Text('맨 앞으로', style: TextStyle(fontSize: 11)),
                ),
                const Spacer(),
                IconButton(
                  tooltip: '선택한 항목 떼기',
                  onPressed: removeSelection,
                  icon: const Icon(
                    Icons.delete_outline,
                    size: 18,
                    color: Color(0xffb26969),
                  ),
                ),
              ],
            ),
            const Divider(color: line),
          ],
          Row(
            children: [
              const Text(
                '스티커 붙이기',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold),
              ),
              const Spacer(),
              IconButton(
                tooltip: '새 스티커 만들기',
                onPressed: createSticker,
                icon: const Icon(Icons.add_circle_outline, size: 20),
              ),
            ],
          ),
          const Text(
            '원하는 스티커를 눌러 주세요',
            style: TextStyle(fontSize: 10, color: blue),
          ),
          const SizedBox(height: 12),
          GridView.builder(
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
              crossAxisCount: 2,
              childAspectRatio: 1,
              crossAxisSpacing: 8,
              mainAxisSpacing: 8,
            ),
            itemCount: stickerAssets.length,
            itemBuilder: (_, i) => InkWell(
              onTap: () => addAsset(stickerAssets[i]),
              child: Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: sky,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Column(
                  children: [
                    Expanded(child: thumbnail(stickerAssets[i])),
                    Text(
                      stickerAssets[i]['name'],
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 9),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    ),
  );
}

class StickerDialog extends StatefulWidget {
  const StickerDialog({super.key});
  @override
  State<StickerDialog> createState() => _StickerDialogState();
}

class _StickerDialogState extends State<StickerDialog> {
  final name = TextEditingController();
  Uint8List? bytes;
  String filename = '', error = '';
  bool keep = false, marked = false, finished = false;
  double ratio = 1;
  Rect box = const Rect.fromLTRB(.05, .05, .95, .95);
  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }

  Future<void> pick() async {
    FocusScope.of(context).unfocus();
    try {
      final result = await FilePicker.platform.pickFiles(
        type: FileType.image,
        withData: true,
      );
      if (result == null || !mounted) return;
      final f = result.files.single;
      if (f.size > 16 * 1024 * 1024) {
        setState(() => error = '사진은 16MB 이하로 선택해 주세요.');
        return;
      }
      final codec = await ui.instantiateImageCodec(f.bytes!);
      final frame = await codec.getNextFrame();
      final value = frame.image.width / frame.image.height;
      frame.image.dispose();
      codec.dispose();
      if (mounted)
        setState(() {
          bytes = f.bytes;
          filename = f.name;
          ratio = value;
          marked = false;
          box = const Rect.fromLTRB(.05, .05, .95, .95);
          error = '';
          if (name.text.isEmpty) name.text = f.name.split('.').first;
        });
    } catch (e) {
      if (mounted)
        setState(() => error = '사진을 열 수 없어요. PNG, JPEG, WebP를 선택해 주세요.');
    }
  }

  void close([Map<String, dynamic>? result]) {
    if (finished || !mounted) return;
    finished = true;
    FocusScope.of(context).unfocus();
    Navigator.of(context, rootNavigator: true).pop(result);
  }

  void submit() {
    if (finished) return;
    if (bytes == null || name.text.trim().isEmpty) {
      setState(() => error = '사진과 스티커 이름을 입력해 주세요.');
      return;
    }
    if (!keep && (!marked || box.width < .02 || box.height < .02)) {
      setState(() => error = '사진에서 굿즈를 감싸는 사각형을 먼저 그려 주세요.');
      return;
    }
    close({
      'name': name.text.trim(),
      'photo': bytes!,
      'filename': filename,
      'fields': <String, String>{
        'name': name.text.trim(),
        'engine': 'sam2-gaussian',
        'background': keep ? 'keep' : 'auto',
        'box': jsonEncode([box.left, box.top, box.right, box.bottom]),
      },
    });
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text('볼록 스티커 만들기'),
        if (error.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              error,
              style: const TextStyle(color: Colors.red, fontSize: 12),
            ),
          ),
      ],
    ),
    content: SizedBox(
      width: 470,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '좋아하는 굿즈가 잘 보이는 사진 한 장을 골라 주세요.',
              style: TextStyle(fontSize: 12, color: blue),
            ),
            const SizedBox(height: 18),
            TextField(
              controller: name,
              maxLength: 60,
              enabled: !finished,
              decoration: const InputDecoration(
                labelText: '스티커 이름',
                hintText: '예: 나의 토끼 키링',
              ),
            ),
            const SizedBox(height: 6),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: finished ? null : pick,
                icon: const Icon(Icons.add_photo_alternate_outlined),
                label: Text(bytes == null ? '사진 선택' : '다른 사진 선택'),
              ),
            ),
            if (bytes != null) ...[
              const SizedBox(height: 12),
              const Text(
                '사진 위는 영역 선택, 사진 밖은 스크롤입니다.',
                style: TextStyle(fontSize: 11, color: blue),
              ),
              const SizedBox(height: 8),
              PhotoSelection(
                key: ValueKey(bytes),
                bytes: bytes!,
                ratio: ratio,
                selection: marked ? box : null,
                enabled: !keep,
                onChanged: (value) => setState(() {
                  box = value;
                  marked = value.width >= .02 && value.height >= .02;
                  error = marked ? '' : '선택 영역을 조금 더 크게 그려 주세요.';
                }),
              ),
              CheckboxListTile(
                value: keep,
                onChanged: (v) => setState(() {
                  keep = v!;
                  error = '';
                }),
                title: const Text(
                  '배경을 포함한 사진 전체로 만들기',
                  style: TextStyle(fontSize: 11),
                ),
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
              ),
            ],
            const SizedBox(height: 12),
            const Text(
              'SAM 2 누끼 → 가우시안 볼록 스티커\n사진과 결과는 내 PC에 저장돼요.',
              style: TextStyle(fontSize: 11, color: blue, height: 1.8),
            ),
          ],
        ),
      ),
    ),
    actions: [
      TextButton(onPressed: () => close(), child: const Text('취소')),
      FilledButton(
        onPressed: bytes == null ? null : submit,
        child: const Text('다음 · 굿즈 연결'),
      ),
    ],
  );
}
