import 'dart:convert';
import 'dart:typed_data';
import 'package:file_picker/file_picker.dart';
import 'package:http/http.dart' as http;
import 'package:material_ui/material_ui.dart';
import 'package:web/web.dart' as web;
import 'api.dart';
import 'nearby.dart';

class LegalPage extends StatelessWidget {
  final Map<String, dynamic> legal;
  final bool privacy;
  const LegalPage({super.key, required this.legal, required this.privacy});
  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: Text(privacy ? '개인정보 처리방침' : '이용약관')),
    body: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: SelectionArea(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final line
                    in (legal[privacy ? 'privacy' : 'terms'] as String).split(
                      '\n',
                    ))
                  Padding(
                    padding: EdgeInsets.only(
                      bottom: line.startsWith('#') ? 12 : 6,
                    ),
                    child: Text(
                      line.replaceFirst(RegExp(r'^#+\s*'), ''),
                      style: TextStyle(
                        fontSize: line.startsWith('#') ? 20 : 14,
                        height: 1.65,
                        fontWeight: line.startsWith('#')
                            ? FontWeight.bold
                            : FontWeight.normal,
                      ),
                    ),
                  ),
                TextButton(
                  onPressed: () =>
                      web.window.open('mailto:${legal['contact']}', '_self'),
                  child: Text('문의: ${legal['contact']}'),
                ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}

class AccountPage extends StatefulWidget {
  final bool onboarding;
  const AccountPage({super.key, this.onboarding = false});
  @override
  State<AccountPage> createState() => _AccountPageState();
}

class _AccountPageState extends State<AccountPage> {
  final name = TextEditingController();
  Map<String, dynamic>? account, legal;
  Uint8List? image, upload;
  bool removePhoto = false,
      busy = false,
      terms = false,
      privacy = false,
      age14 = false,
      done = false;
  String? error;
  bool get needsSetup => account?['profile_ready'] != true;
  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final values = await Future.wait([
        Api.get('/auth/me'),
        Api.get('/auth/legal'),
      ]);
      final me = Map<String, dynamic>.from(values[0]);
      Uint8List? photo;
      if (me['has_avatar'] == true) {
        final response = await http
            .get(Api.uri('/auth/avatar'), headers: Api.headers)
            .timeout(const Duration(seconds: 15));
        if (response.statusCode == 200) photo = response.bodyBytes;
      }
      if (!mounted) return;
      setState(() {
        account = me;
        legal = Map<String, dynamic>.from(values[1]);
        image = photo;
        name.text = me['name'] == '새 수집가' ? '' : me['name'] ?? '';
      });
    } catch (_) {
      if (mounted) setState(() => error = '계정 정보를 불러오지 못했어요. 서버 연결을 확인해 주세요.');
    }
  }

  Future<void> choosePhoto() async {
    final chosen = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['jpg', 'jpeg', 'png', 'webp'],
      withData: true,
    );
    if (!mounted || chosen == null) return;
    final bytes = chosen.files.single.bytes;
    if (bytes == null || bytes.length > 2 * 1024 * 1024) {
      setState(() => error = '사진은 2MB 이하로 선택해 주세요.');
      return;
    }
    setState(() {
      image = bytes;
      upload = bytes;
      removePhoto = false;
      error = null;
    });
  }

  Future<void> save() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await Api.post('/auth/profile', {
        'nickname': name.text.trim(),
        'photo': upload == null ? null : base64Encode(upload!),
        'remove_photo': removePhoto,
        'terms': terms,
        'privacy': privacy,
        'age14': age14,
        'policy_version': legal!['version'],
      });
      if (!mounted) return;
      setState(() => done = true);
      Navigator.pop(context, true);
    } catch (e) {
      if (mounted)
        setState(() => error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> reauthenticate() async {
    if (legal == null) return;
    try {
      NearbyController.instance.stop();
      await Api.socialLogin(
        account!['provider'],
        false,
        legal!['version'],
        true,
        true,
        true,
      );
    } catch (e) {
      if (mounted)
        setState(() => error = e.toString().replaceFirst('Exception: ', ''));
    }
  }

  Future<void> withdraw() async {
    final confirm = TextEditingController();
    bool checked = false;
    final expected = account?['profile_created'] == true
        ? account!['name'] as String
        : '회원탈퇴';
    final accepted = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, update) => AlertDialog(
          title: const Text('정말 탈퇴하시겠어요?'),
          content: SizedBox(
            width: 360,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text(
                    '계정·프로필 사진·에셋·다이어리·휴지통·검색 기록을 삭제하고 모든 로그인과 위치 공유를 종료해요. 복구할 수 없어요. 관리 백업은 최대 7일 후 삭제되며 삭제 실패는 자동 재시도해요.',
                  ),
                  const SizedBox(height: 12),
                  Text('확인을 위해 "$expected"을 정확히 입력해 주세요.'),
                  TextField(
                    controller: confirm,
                    onChanged: (_) => update(() {}),
                    decoration: const InputDecoration(labelText: '탈퇴 확인 문구'),
                  ),
                  CheckboxListTile(
                    value: checked,
                    onChanged: (value) =>
                        update(() => checked = value ?? false),
                    title: const Text('삭제 범위와 복구 불가 안내를 확인했어요.'),
                  ),
                ],
              ),
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('취소'),
            ),
            FilledButton(
              onPressed: checked && confirm.text == expected
                  ? () => Navigator.pop(ctx, true)
                  : null,
              child: const Text('회원탈퇴'),
            ),
          ],
        ),
      ),
    );
    final text = confirm.text;
    confirm.dispose();
    if (accepted != true || !mounted) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await Api.post('/auth/delete', {
        'confirmation': text,
        'acknowledged': true,
      });
      NearbyController.instance.stop();
      Api.clearAfterWithdrawal();
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (ctx) => PopScope(
          canPop: false,
          child: AlertDialog(
            title: Text(result['pending'] == true ? '탈퇴 접수 완료' : '탈퇴 완료'),
            content: Text(
              '${result['message']}\n\n${result['provider_unlinked'] == true ? '소셜 서비스 연결도 해제했어요.' : '소셜 서비스 연결 해제를 확인하지 못했어요. Google·카카오·네이버의 연결된 서비스 설정에서도 해제해 주세요.'}\n\n이 브라우저의 굿모닝 저장 정보를 초기화해요. 다른 굿모닝 탭도 닫아 주세요.',
            ),
            actions: [
              FilledButton(
                onPressed: () => web.window.location.replace(Uri.base.path),
                child: const Text('처음으로'),
              ),
            ],
          ),
        ),
      );
    } catch (e) {
      if (mounted)
        setState(() => error = e.toString().replaceFirst('Exception: ', ''));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !widget.onboarding || done,
    child: Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: !widget.onboarding,
        title: Text(needsSetup ? '처음 만나요 · 프로필 설정' : '계정 설정'),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (account == null && error == null)
                  const LinearProgressIndicator(),
                if (account != null) ...[
                  Center(
                    child: ClipOval(
                      child: image == null
                          ? const CircleAvatar(
                              radius: 48,
                              child: Icon(Icons.person, size: 56),
                            )
                          : Image.memory(
                              image!,
                              width: 96,
                              height: 96,
                              fit: BoxFit.cover,
                              errorBuilder: (_, __, ___) =>
                                  const Icon(Icons.broken_image, size: 64),
                            ),
                    ),
                  ),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      TextButton(
                        onPressed: busy ? null : choosePhoto,
                        child: const Text('사진 선택'),
                      ),
                      TextButton(
                        onPressed: busy
                            ? null
                            : () => setState(() {
                                image = null;
                                upload = null;
                                removePhoto = true;
                              }),
                        child: const Text('기본 이미지'),
                      ),
                    ],
                  ),
                  const Text(
                    '사진은 선택 사항이에요. 기본 이미지로도 가입할 수 있어요. 올린 사진은 256px로 다시 만들고 위치 등 메타데이터를 제거해요.',
                    style: TextStyle(fontSize: 12, height: 1.6),
                  ),
                  const SizedBox(height: 20),
                  TextField(
                    controller: name,
                    maxLength: 20,
                    enabled: !busy,
                    decoration: const InputDecoration(
                      labelText: '닉네임',
                      helperText: '실명 대신 별명을 사용해 주세요. 2~20자',
                    ),
                  ),
                  if (legal != null) ...[
                    Wrap(
                      spacing: 8,
                      children: [
                        TextButton(
                          onPressed: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) =>
                                  LegalPage(legal: legal!, privacy: false),
                            ),
                          ),
                          child: const Text('이용약관'),
                        ),
                        TextButton(
                          onPressed: () => Navigator.push(
                            context,
                            MaterialPageRoute(
                              builder: (_) =>
                                  LegalPage(legal: legal!, privacy: true),
                            ),
                          ),
                          child: const Text('개인정보 처리방침'),
                        ),
                      ],
                    ),
                    if (needsSetup) ...[
                      CheckboxListTile(
                        value: terms,
                        onChanged: busy
                            ? null
                            : (v) => setState(() => terms = v ?? false),
                        title: const Text('[필수] 이용약관에 동의해요.'),
                      ),
                      CheckboxListTile(
                        value: privacy,
                        onChanged: busy
                            ? null
                            : (v) => setState(() => privacy = v ?? false),
                        title: const Text('[필수] 개인정보 수집·이용 안내를 확인하고 동의해요.'),
                      ),
                      CheckboxListTile(
                        value: age14,
                        onChanged: busy
                            ? null
                            : (v) => setState(() => age14 = v ?? false),
                        title: const Text('[필수] 만 14세 이상이에요.'),
                      ),
                    ],
                    FilledButton(
                      onPressed:
                          busy || needsSetup && !(terms && privacy && age14)
                          ? null
                          : save,
                      child: Text(needsSetup ? '프로필 설정 완료' : '변경 저장'),
                    ),
                  ],
                  const SizedBox(height: 24),
                  const Text(
                    '서비스에 필요한 최소 항목만 처리하고, 계정별 접근 제한·사진 메타데이터 제거·세션 만료·탈퇴 삭제를 적용해요. 상세 범위와 외부 서비스 경유는 개인정보 처리방침에서 확인해 주세요.',
                    style: TextStyle(fontSize: 13, height: 1.6),
                  ),
                  const SizedBox(height: 20),
                  OutlinedButton(
                    onPressed: busy
                        ? null
                        : () async {
                            NearbyController.instance.stop();
                            try {
                              await Api.logout();
                            } catch (_) {
                              if (mounted)
                                setState(
                                  () => error = '로그아웃하지 못했어요. 다시 시도해 주세요.',
                                );
                            }
                          },
                    child: const Text('로그아웃'),
                  ),
                  TextButton(
                    onPressed: busy ? null : reauthenticate,
                    child: const Text('탈퇴 전 소셜 계정 다시 확인'),
                  ),
                  TextButton(
                    onPressed: busy ? null : withdraw,
                    child: const Text(
                      '회원탈퇴',
                      style: TextStyle(color: Colors.red),
                    ),
                  ),
                  const Text(
                    '탈퇴는 소셜 로그인 후 10분 안에 진행할 수 있어요. 진행 중인 생성·검색 작업이 있으면 끝난 뒤 다시 시도해 주세요.',
                    style: TextStyle(fontSize: 12, height: 1.6),
                  ),
                ],
                if (busy) const LinearProgressIndicator(),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: Text(
                      error!,
                      style: const TextStyle(color: Colors.red),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
