#import <Foundation/Foundation.h>
#import <CommonCrypto/CommonDigest.h>
#import <ImageIO/ImageIO.h>
#import <PDFKit/PDFKit.h>

static NSString *PCSHA(NSData *data) {
    unsigned char bytes[CC_SHA256_DIGEST_LENGTH];
    CC_SHA256(data.bytes, (CC_LONG)data.length, bytes);
    NSMutableString *result = [NSMutableString string];
    for (NSUInteger i = 0; i < sizeof(bytes); i++) [result appendFormat:@"%02x", bytes[i]];
    return result;
}

static NSData *PCFileData(NSDictionary *spec, BOOL allowPDF, NSUInteger *width, NSUInteger *height) {
    if (![spec isKindOfClass:NSDictionary.class]) return nil;
    NSString *name = spec[@"filename"], *encoded = spec[@"content_base64"], *mime = spec[@"media_type"];
    if (![name isKindOfClass:NSString.class] || name.length == 0 || name.length > 150 ||
        [name rangeOfCharacterFromSet:[NSCharacterSet characterSetWithCharactersInString:@"/\\:"]].location != NSNotFound ||
        [name rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound ||
        ![encoded isKindOfClass:NSString.class] || encoded.length > 2796204) return nil;
    NSData *data = [[NSData alloc] initWithBase64EncodedString:encoded options:0];
    if (!data || data.length == 0 || data.length > 2097152 || ![PCSHA(data) isEqual:spec[@"sha256"]]) return nil;
    NSString *ext = name.pathExtension.lowercaseString;
    if ([mime isEqual:@"application/pdf"] && allowPDF && [ext isEqual:@"pdf"]) {
        PDFDocument *document = [[PDFDocument alloc] initWithData:data];
        return document && !document.isEncrypted && document.pageCount > 0 ? data : nil;
    }
    if (!(([mime isEqual:@"image/png"] && [ext isEqual:@"png"]) ||
          ([mime isEqual:@"image/jpeg"] && ([@[@"jpg", @"jpeg"] containsObject:ext])))) return nil;
    CGImageSourceRef image = CGImageSourceCreateWithData((__bridge CFDataRef)data, NULL);
    if (!image) return nil;
    NSDictionary *properties = CFBridgingRelease(CGImageSourceCopyPropertiesAtIndex(image, 0, NULL));
    NSString *uti = (__bridge NSString *)CGImageSourceGetType(image);
    BOOL typeOK = [uti isEqual:([mime isEqual:@"image/png"] ? @"public.png" : @"public.jpeg")];
    *width = [properties[(__bridge NSString *)kCGImagePropertyPixelWidth] unsignedIntegerValue];
    *height = [properties[(__bridge NSString *)kCGImagePropertyPixelHeight] unsignedIntegerValue];
    if (!typeOK || *width == 0 || *height == 0 || *width > 16384 || *height > 16384 || *width * *height > 40000000) {
        CFRelease(image); return nil;
    }
    CGImageRef decoded = CGImageSourceCreateImageAtIndex(image, 0, NULL);
    CFRelease(image);
    if (!decoded) return nil;
    CGImageRelease(decoded);
    return data;
}

static NSData *PCLocalBytes(NSURL *url) {
    if (![url isKindOfClass:NSURL.class] || !url.isFileURL) return nil;
    BOOL scoped = [url startAccessingSecurityScopedResource];
    NSNumber *size = nil;
    NSData *data = nil;
    if ([url getResourceValue:&size forKey:NSURLFileSizeKey error:nil] && size.unsignedLongLongValue <= 4194304)
        data = [NSData dataWithContentsOfURL:url options:0 error:nil];
    if (scoped) [url stopAccessingSecurityScopedResource];
    return data;
}
