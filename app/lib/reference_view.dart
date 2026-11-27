import 'dart:js_interop';
import 'dart:ui_web' as ui_web;
import 'package:material_ui/material_ui.dart';
import 'package:web/web.dart' as web;
import 'api.dart';

/// Original prototype's home, browse pages and navigation in the Flutter app.
class ReferenceView extends StatefulWidget {
  final bool navigationOnly;
  final int tab;
  final ValueChanged<int> onNavigate;
  final bool connectionReady;
  final String? connectionError, pendingAsset, diaryId;
  final ValueChanged<String>? onAssetAdded, onError;
  final VoidCallback? onAccount, onNearby;
  final bool nearbyActive;
  final String accountLabel;
  const ReferenceView({
    super.key,
    this.navigationOnly = false,
    this.tab = 0,
    required this.onNavigate,
    this.connectionReady = false,
    this.connectionError,
    this.pendingAsset,
    this.diaryId,
    this.onAssetAdded,
    this.onError,
    this.onAccount,
    this.onNearby,
    this.nearbyActive = false,
    this.accountLabel = '로그인',
  });
  @override
  State<ReferenceView> createState() => _ReferenceViewState();
}

class _ReferenceViewState extends State<ReferenceView> {
  static int count = 0;
  late final String viewType;
  late final web.HTMLIFrameElement frame;
  late final JSFunction listener;
  @override
  void initState() {
    super.initState();
    viewType = 'reference-${count++}';
    frame = web.HTMLIFrameElement()
      ..allow = 'accelerometer; gyroscope; fullscreen'
      ..src = Api.staticUri(
        widget.navigationOnly
            ? 'reference/nav.html?tab=${widget.tab}'
            : 'reference/index.html?${widget.tab == 3
                  ? 'browse'
                  : widget.tab == 2
                  ? 'magnets'
                  : 'home'}',
      ).toString()
      ..title = (widget.navigationOnly
          ? '굿모닝 메뉴'
          : widget.tab == 3
          ? '훔쳐보기'
          : widget.tab == 2
          ? '내 다이어리'
          : '내 금고')
      ..style.border = 'none'
      ..style.width = '100%'
      ..style.height = '100%';
    ui_web.platformViewRegistry.registerViewFactory(viewType, (_) => frame);
    listener = ((web.MessageEvent event) {
      if (event.origin != Uri.base.origin ||
          event.source != frame.contentWindow)
        return;
      final data = event.data.dartify();
      if (data is Map && data['source'] == 'goodmorning-reference') {
        if (data['type'] == 'ready') sync();
        if (data['type'] == 'account') widget.onAccount?.call();
        if (data['type'] == 'nearby') widget.onNearby?.call();
        if (data['type'] == 'asset-added')
          widget.onAssetAdded?.call(data['id'].toString());
        if (data['type'] == 'error')
          widget.onError?.call(data['message'].toString());
      }
      if (data is Map &&
          data['source'] == 'goodmorning-reference' &&
          data['tab'] is int) {
        final tab = data['tab'] as int;
        if (tab >= 0 && tab <= 3) widget.onNavigate(tab);
      }
    }).toJS;
    web.window.addEventListener('message', listener);
  }

  void sync() {
    frame.contentWindow?.postMessage(
      {
        'source': 'goodmorning-app',
        'type': 'connection',
        'ready': widget.connectionReady,
        'error': widget.connectionReady ? null : widget.connectionError,
        'apiBase': Api.uri('/').origin,
        'headers': Api.headers,
        'pendingAsset': widget.pendingAsset,
        'diaryId': widget.diaryId,
        'accountLabel': widget.accountLabel,
        'nearbyActive': widget.nearbyActive,
      }.jsify(),
      Uri.base.origin.toJS,
    );
  }

  @override
  void didUpdateWidget(covariant ReferenceView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.tab != widget.tab ||
        oldWidget.connectionError != null && widget.connectionError == null)
      frame.src = Api.staticUri(
        widget.navigationOnly
            ? 'reference/nav.html?tab=${widget.tab}'
            : 'reference/index.html?${widget.tab == 3
                  ? 'browse'
                  : widget.tab == 2
                  ? 'magnets'
                  : 'home'}',
      ).toString();
    sync();
  }

  @override
  void dispose() {
    web.window.removeEventListener('message', listener);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => HtmlElementView(viewType: viewType);
}
