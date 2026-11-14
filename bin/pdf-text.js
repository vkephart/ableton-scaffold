ObjC.import('PDFKit');
ObjC.import('Foundation');
function run(argv) {
  var url = $.NSURL.fileURLWithPath(argv[0]);
  var doc = $.PDFDocument.alloc.initWithURL(url);
  var n = doc.pageCount;
  var out = '';
  for (var i = 0; i < n; i++) {
    var s = doc.pageAtIndex(i).string;
    out += '\n=====PAGE ' + (i + 1) + '=====\n' + (s.js || '');
  }
  $(out).writeToFileAtomicallyEncodingError(argv[1], true, $.NSUTF8StringEncoding, null);
  return n + ' pages';
}
