import 'dart:async';
import 'dart:js_interop';
import 'dart:convert';
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'package:web/web.dart' as web;

class Api {
  static String base = const String.fromEnvironment('API_BASE');
  static String token = '';
  static bool _automaticReady = false;
  static final _images = <String, Future<Uint8List>>{};
  static bool get hosted => Uri.base.host.endsWith('github.io');
  static bool get configured => base.isNotEmpty || !hosted;
  static Map<String, String> get headers =>
      token.isEmpty ? {} : {'Authorization': 'Bearer $token'};
  static void clearAfterWithdrawal() {
    web.window.localStorage.setItem('goodmorning-clear-browser', '1');
    token = '';
    _images.clear();
    web.window.sessionStorage.removeItem('goodmorning-token');
    web.window.sessionStorage.removeItem('goodmorning-oauth');
  }

  static Future<void> initialize() async {
    if (web.window.localStorage.getItem('goodmorning-clear-browser') == '1') {
      for (final storage in [
        web.window.localStorage,
        web.window.sessionStorage,
      ]) {
        final keys = <String>[];
        for (var i = 0; i < storage.length; i++) {
          final key = storage.key(i);
          if (key != null &&
              key.startsWith('goodmorning-') &&
              key != 'goodmorning-clear-browser')
            keys.add(key);
        }
        for (final key in keys) {
          storage.removeItem(key);
        }
      }
      for (final database in [
        'goodmorning-diary-demo',
        'goodmorning-3d-post',
        'goodmorning-sticker-library',
      ]) {
        final completed = Completer<void>();
        final request = web.window.indexedDB.deleteDatabase(database);
        request.addEventListener(
          'success',
          ((web.Event _) {
            if (!completed.isCompleted) completed.complete();
          }).toJS,
        );
        void failed(web.Event _) {
          if (!completed.isCompleted)
            completed.completeError(
              Exception('브라우저 저장 정보 삭제가 지연되고 있어요. 다른 굿모닝 탭을 모두 닫고 새로고침해 주세요.'),
            );
        }

        request.addEventListener('error', failed.toJS);
        request.addEventListener('blocked', failed.toJS);
        await completed.future.timeout(const Duration(seconds: 15));
      }
    }
    web.window.localStorage.removeItem('goodmorning-clear-browser');
    // Only ordinary user sessions belong in the public app. Legacy owner links
    // must never restore administrator credentials or override server discovery.
    token = userSession(web.window.sessionStorage.getItem('goodmorning-token'));
    if (token.isEmpty)
      web.window.sessionStorage.removeItem('goodmorning-token');
    web.window.localStorage.removeItem('goodmorning-api');
    if (Uri.base.fragment.isNotEmpty) {
      web.window.history.replaceState(
        null,
        '',
        '${Uri.base.path}${Uri.base.hasQuery ? '?${Uri.base.query}' : ''}',
      );
    }
  }

  static String userSession(String? value) =>
      value != null &&
          (value.startsWith('guest.') || value.startsWith('member.'))
      ? value
      : '';

  static void resetConnection() {
    _automaticReady = false;
  }

  static String errorMessage(Object error) {
    if (error is http.ClientException ||
        error is TimeoutException ||
        error is FormatException) {
      return '연결이 원활하지 않아요. 잠시 후 다시 시도해 주세요.';
    }
    return error.toString().replaceFirst('Exception: ', '');
  }

  static Future<void> autoConnect() async {
    if (!hosted || _automaticReady) return;
    final configResponse = await http
        .get(
          staticUri('runtime-config.json').replace(
            queryParameters: {
              'v': DateTime.now().millisecondsSinceEpoch.toString(),
            },
          ),
        )
        .timeout(const Duration(seconds: 15));
    if (configResponse.statusCode != 200)
      throw Exception('자동 연결 정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.');
    final config = jsonDecode(configResponse.body) as Map<String, dynamic>;
    final address = config['apiBase'] as String? ?? '';
    if (address.isEmpty) throw Exception('서비스 연결을 준비 중이에요. 잠시 후 다시 시도해 주세요.');
    final visitorToken = userSession(
      web.window.localStorage.getItem('goodmorning-visitor-token'),
    );
    if (visitorToken.isEmpty)
      web.window.localStorage.removeItem('goodmorning-visitor-token');
    // Restore an unclaimed visitor collection after an expired member session.
    // Do not overwrite that collection's capability with a new guest token.
    for (final candidate in {
      token,
      visitorToken,
    }.where((value) => value.isNotEmpty)) {
      _configure(address, candidate);
      final response = await http
          .get(uri('/auth/me'), headers: headers)
          .timeout(const Duration(seconds: 20));
      if (response.statusCode == 200) {
        _automaticReady = true;
        return;
      }
      if (![401, 403].contains(response.statusCode))
        throw Exception('잠시 연결이 끊겼어요. 다시 시도해 주세요.');
    }
    _configure(address, '');
    final response = await http
        .post(uri('/auth/guest'))
        .timeout(const Duration(seconds: 20));
    final result = check(response) as Map<String, dynamic>;
    token = result['token'] as String;
    web.window.localStorage.setItem('goodmorning-visitor-token', token);
    web.window.sessionStorage.setItem('goodmorning-token', token);
    _automaticReady = true;
  }

  static void _configure(String server, String key) {
    final parsed = Uri.tryParse(server.trim());
    if (parsed == null ||
        !parsed.hasAuthority ||
        !(parsed.scheme == 'https' ||
            parsed.scheme == 'http' &&
                ['localhost', '127.0.0.1'].contains(parsed.host)) ||
        parsed.userInfo.isNotEmpty ||
        parsed.hasQuery ||
        parsed.hasFragment ||
        !['', '/'].contains(parsed.path)) {
      throw const FormatException('서비스 연결 정보를 확인하지 못했어요.');
    }
    base = parsed.origin;
    token = key.trim();
    _images.clear();
    web.window.sessionStorage.setItem('goodmorning-token', token);
  }

  static Future<void> socialLogin(
    String provider,
    bool keepGuest,
    String policyVersion,
    bool terms,
    bool privacy,
    bool age14,
  ) async {
    if (!['google', 'kakao'].contains(provider))
      throw Exception('지원하지 않는 로그인 방식이에요.');
    final providers = await get('/auth/providers');
    final callback = Uri.parse(providers[provider]['callback_url'] as String);
    if (callback.origin != Uri.base.origin)
      throw Exception('공개 웹 주소에서 로그인을 이용해 주세요.');
    final result = await post('/auth/$provider/start', {
      'keep_guest': keepGuest,
      'policy_version': policyVersion,
      'terms': terms,
      'privacy': privacy,
      'age14': age14,
    });
    web.window.sessionStorage.setItem(
      'goodmorning-oauth',
      jsonEncode({
        'provider': provider,
        'state': result['state'],
        'verifier': result['verifier'],
        'server': uri('/').origin,
        'guestToken': token.startsWith('guest.') ? token : '',
        'expires': DateTime.now().millisecondsSinceEpoch + 600000,
      }),
    );
    web.window.location.assign(result['authorize_url'] as String);
  }

  static Future<void> logout() async {
    await post('/auth/logout');
    web.window.sessionStorage.removeItem('goodmorning-token');
    web.window.sessionStorage.removeItem('goodmorning-oauth');
    web.window.location.reload();
  }

  static Uri staticUri(String path) {
    final uri = Uri.base.resolve(path);
    final revision = web.document.documentElement?.getAttribute('data-build');
    return revision == null
        ? uri
        : uri.replace(
            queryParameters: {...uri.queryParameters, '_build': revision},
          );
  }

  static Future<Uint8List> image(String path) =>
      _images.putIfAbsent(path, () async {
        final response = await http
            .get(uri(path), headers: headers)
            .timeout(const Duration(seconds: 30));
        if (response.statusCode != 200) {
          _images.remove(path);
          throw Exception('이미지를 불러오지 못했어요.');
        }
        return response.bodyBytes;
      });
  static Uri uri(String path) =>
      Uri.parse('${base.isEmpty ? Uri.base.origin : base}$path');
  static dynamic check(http.Response response) {
    if (response.statusCode == 401 || response.statusCode == 403) {
      _automaticReady = false;
      throw Exception('접속이 만료됐어요. 다시 연결하거나 로그인해 주세요.');
    }
    final dynamic data;
    try {
      data = jsonDecode(utf8.decode(response.bodyBytes));
    } catch (_) {
      throw Exception('서비스 응답을 읽지 못했어요. 잠시 후 다시 시도해 주세요.');
    }
    if (response.statusCode >= 400) {
      throw Exception(
        data is Map && data['detail'] is String
            ? data['detail']
            : '요청을 처리하지 못했어요. (${response.statusCode})',
      );
    }
    return data;
  }

  static Future<dynamic> get(String path) async => check(
    await http
        .get(uri(path), headers: headers)
        .timeout(const Duration(seconds: 20)),
  );
  static Future<dynamic> save(Map<String, dynamic> diary) async => check(
    await http
        .put(
          uri('/api/diaries/${diary['id']}'),
          headers: {...headers, 'Content-Type': 'application/json'},
          body: jsonEncode(diary),
        )
        .timeout(const Duration(seconds: 20)),
  );
  static Future<dynamic> post(
    String path, [
    Map<String, dynamic> body = const {},
  ]) async => check(
    await http
        .post(
          uri(path),
          headers: {...headers, 'Content-Type': 'application/json'},
          body: jsonEncode(body),
        )
        .timeout(const Duration(seconds: 20)),
  );
  static Future<dynamic> upload(
    String path,
    Uint8List bytes,
    String filename,
    Map<String, String> fields,
  ) async {
    final request = http.MultipartRequest('POST', uri(path))
      ..headers.addAll(headers)
      ..fields.addAll(fields)
      ..files.add(
        http.MultipartFile.fromBytes('photo', bytes, filename: filename),
      );
    return check(
      await http.Response.fromStream(
        await request.send().timeout(const Duration(seconds: 60)),
      ),
    );
  }
}
