// Reverse-geocodes one private JSON coordinate via the system Apple service.
// Receives stdin instead of process arguments; prints no coordinates.
import Foundation
import CoreLocation

@main struct LocationGeocoder {
    static func main() async {
        do {
            let raw = FileHandle.standardInput.readDataToEndOfFile()
            guard raw.count < 4096,
                  let input = try JSONSerialization.jsonObject(with: raw) as? [String: Double],
                  let lat = input["latitude"], let lon = input["longitude"],
                  lat.isFinite, lon.isFinite, abs(lat) <= 90, abs(lon) <= 180 else {
                exit(2)
            }
            let geocoder = CLGeocoder()
            let marks = try await geocoder.reverseGeocodeLocation(CLLocation(latitude: lat, longitude: lon))
            guard let p = marks.first else { exit(3) }
            var output: [String: String] = ["provider": "Apple Maps reverse geocoder"]
            output["name"] = p.name
            output["address"] = [p.subThoroughfare, p.thoroughfare, p.locality, p.administrativeArea, p.postalCode].compactMap { $0 }.joined(separator: " ")
            output["locality"] = p.locality
            output["country"] = p.country
            let data = try JSONSerialization.data(withJSONObject: output, options: [.sortedKeys])
            FileHandle.standardOutput.write(data)
        } catch { exit(1) }
    }
}
