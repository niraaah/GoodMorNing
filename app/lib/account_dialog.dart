import 'package:material_ui/material_ui.dart';
import 'api.dart';
import 'account_page.dart';

class AccountDialog extends StatefulWidget {
  const AccountDialog({super.key});
  @override
  State<AccountDialog> createState() => _AccountDialogState();
}

class _AccountDialogState extends State<AccountDialog> {
  Map<String, dynamic>? account, providers, legal;
  bool busy = false,
      keepGuest = false,
      terms = false,
      privacy = false,
      age14 = false;
  String? error;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      await Api.autoConnect();
      final values = await Future.wait([
        Api.get('/auth/me'),
        Api.get('/auth/providers'),
        Api.get('/auth/legal'),
      ]);
      if (mounted)
        setState(() {
          account = Map<String, dynamic>.from(values[0]);
          providers = Map<String, dynamic>.from(values[1]);
          legal = Map<String, dynamic>.from(values[2]);
        });
    } catch (_) {
      if (mounted) setState(() => error = '로그인 정보를 불러오지 못했어요. 서버 연결을 확인해 주세요.');
    }
  }

  Future<void> login(String provider) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await Api.socialLogin(
        provider,
        keepGuest,
        legal!['version'],
        terms,
        privacy,
        age14,
      );
    } catch (e) {
      if (mounted)
        setState(() {
          busy = false;
          error = e.toString().replaceFirst('Exception: ', '');
        });
    }
  }

  Future<void> logout() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await Api.logout();
    } catch (_) {
      if (mounted)
        setState(() {
          busy = false;
          error = '로그아웃하지 못했어요. 연결 후 다시 시도해 주세요.';
        });
    }
  }

  @override
  Widget build(BuildContext context) {
    final member = account?['kind'] == 'member';
    return AlertDialog(
      title: Text(member ? '내 계정' : '내 수집방 로그인'),
      content: SizedBox(
        width: 340,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (account == null && error == null)
                const Center(child: CircularProgressIndicator()),
              if (member) ...[
                Text('${account!['name']}님'),
                const SizedBox(height: 12),
                const Text('로그아웃해도 계정에 저장한 에셋과 다이어리는 남아 있어요.'),
                const SizedBox(height: 20),
                OutlinedButton(
                  onPressed: busy ? null : logout,
                  child: const Text('로그아웃'),
                ),
              ] else if (providers != null) ...[
                const Text('구글·카카오·네이버 계정으로 나의 에셋과 다이어리를 이어서 사용해 보세요.'),
                const SizedBox(height: 16),
                if (legal != null) ...[
                  Wrap(
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
                  const Text(
                    '필수 항목: 소셜 서비스 식별번호, 닉네임, 로그인·동의 기록. 목적: 계정 확인·자료 보관·보안. 보유: 탈퇴까지(세부 삭제·백업 기간은 방침 참고). 동의를 거부할 수 있으나 회원 기능은 이용할 수 없어요. 사진은 선택 사항이에요.',
                    style: TextStyle(fontSize: 12, height: 1.5),
                  ),
                  CheckboxListTile(
                    value: terms,
                    onChanged: busy
                        ? null
                        : (v) => setState(() => terms = v ?? false),
                    title: const Text('[필수] 이용약관 동의'),
                  ),
                  CheckboxListTile(
                    value: privacy,
                    onChanged: busy
                        ? null
                        : (v) => setState(() => privacy = v ?? false),
                    title: const Text('[필수] 개인정보 수집·이용 동의'),
                  ),
                  CheckboxListTile(
                    value: age14,
                    onChanged: busy
                        ? null
                        : (v) => setState(() => age14 = v ?? false),
                    title: const Text('[필수] 만 14세 이상'),
                  ),
                ],
                for (final provider in ['google', 'kakao', 'naver'])
                  Padding(
                    padding: const EdgeInsets.only(bottom: 10),
                    child: OutlinedButton(
                      onPressed:
                          !busy &&
                              terms &&
                              privacy &&
                              age14 &&
                              providers![provider]?['enabled'] == true
                          ? () => login(provider)
                          : null,
                      style: OutlinedButton.styleFrom(
                        backgroundColor: provider == 'naver'
                            ? const Color(0xff03a94d)
                            : provider == 'kakao'
                            ? const Color(0xfffee500)
                            : Colors.white,
                        foregroundColor: const Color(0xff1f1f1f),
                        padding: EdgeInsets.symmetric(
                          vertical: provider == 'naver' ? 0 : 16,
                        ),
                      ),
                      child: provider == 'naver'
                          ? Column(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Image.asset(
                                  'assets/naver-login.png',
                                  height: 48,
                                  fit: BoxFit.contain,
                                  semanticLabel: '네이버 로그인',
                                ),
                                if (providers![provider]?['enabled'] != true)
                                  const Padding(
                                    padding: EdgeInsets.only(bottom: 6),
                                    child: Text(
                                      '준비 중',
                                      style: TextStyle(color: Colors.white),
                                    ),
                                  ),
                              ],
                            )
                          : Text(
                              '${provider == 'google' ? 'Google 계정으로 로그인' : '카카오 로그인'}${providers![provider]?['enabled'] == true ? '' : ' · 준비 중'}',
                            ),
                    ),
                  ),
                if (account?['kind'] == 'guest') ...[
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    value: keepGuest,
                    onChanged: busy
                        ? null
                        : (value) => setState(() => keepGuest = value ?? false),
                    title: const Text(
                      '처음 가입할 때 현재 방문자 자료 가져오기',
                      style: TextStyle(fontSize: 14),
                    ),
                  ),
                  const Text(
                    '이미 가입한 계정에는 합쳐지지 않아요. 로그인 서비스가 다르면 별도의 수집방으로 연결돼요.',
                    style: TextStyle(fontSize: 12),
                  ),
                ],
              ],
              if (busy)
                const Padding(
                  padding: EdgeInsets.only(top: 16),
                  child: LinearProgressIndicator(),
                ),
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
      actions: [
        TextButton(
          onPressed: busy ? null : () => Navigator.pop(context),
          child: const Tooltip(
            message: '닫기',
            child: Icon(Icons.close, semanticLabel: '닫기'),
          ),
        ),
      ],
    );
  }
}
