#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

struct Point {
    double x;
    double y;
    double z;
    double count;
};

struct Pixel {
    double smoothed = 0;
    double background = 0;
    double contrast = 0;
    double score = 0;
};

double median(std::vector<double> values) {
    auto midpoint = values.begin() + values.size() / 2;
    std::nth_element(values.begin(), midpoint, values.end());
    if (values.size() % 2 == 1) return *midpoint;
    return (*midpoint + *std::max_element(values.begin(), midpoint)) / 2;
}

std::vector<Point> read_scan(const char* path) {
    std::ifstream input(path);
    std::string line;
    if (!std::getline(input, line) || line != "x_um,y_um,z_um,count_kcps") {
        throw std::runtime_error("Expected CSV header: x_um,y_um,z_um,count_kcps");
    }
    std::vector<Point> points;
    while (std::getline(input, line)) {
        std::replace(line.begin(), line.end(), ',', ' ');
        std::istringstream row(line);
        Point point{};
        std::string extra;
        if (!(row >> point.x >> point.y >> point.z >> point.count) || row >> extra ||
            !std::isfinite(point.x) || !std::isfinite(point.y) ||
            !std::isfinite(point.z) || !std::isfinite(point.count) || point.count < 0) {
            throw std::runtime_error("Invalid scan row " + std::to_string(points.size() + 2));
        }
        points.push_back(point);
    }
    if (points.empty()) throw std::runtime_error("Scan has no data");
    return points;
}

std::vector<double> coordinates(const std::vector<Point>& points, double Point::*axis) {
    std::vector<double> values;
    for (const Point& point : points) values.push_back(point.*axis);
    std::sort(values.begin(), values.end());
    values.erase(std::unique(values.begin(), values.end()), values.end());
    return values;
}

int run(const char* input_path, const char* image_path) {
    const auto points = read_scan(input_path);
    const auto x_axis = coordinates(points, &Point::x);
    const auto y_axis = coordinates(points, &Point::y);
    const int width = static_cast<int>(x_axis.size());
    const int height = static_cast<int>(y_axis.size());
    if (width < 9 || height < 9 || points.size() != x_axis.size() * y_axis.size()) {
        throw std::runtime_error("Expected a complete XY grid with at least 9 rows and 9 columns");
    }
    const auto index = [width](int x, int y) { return y * width + x; };
    const auto inside = [width, height](int x, int y) {
        return x >= 0 && x < width && y >= 0 && y < height;
    };
    const double z = points.front().z;
    std::vector<double> raw(points.size(), -1);
    for (const Point& point : points) {
        const int x = static_cast<int>(std::lower_bound(x_axis.begin(), x_axis.end(), point.x) - x_axis.begin());
        const int y = static_cast<int>(std::lower_bound(y_axis.begin(), y_axis.end(), point.y) - y_axis.begin());
        double& count = raw[index(x, y)];
        if (count >= 0 || std::abs(point.z - z) > 1e-6) {
            throw std::runtime_error("Expected one measurement per XY coordinate at constant Z");
        }
        count = point.count;
    }
    std::vector<Pixel> pixels(raw.size());

    // A small weighted average limits isolated spikes while retaining compact spots.
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            double sum = 0;
            int total_weight = 0;
            for (int dy = -1; dy <= 1; ++dy) {
                for (int dx = -1; dx <= 1; ++dx) {
                    if (!inside(x + dx, y + dy)) continue;
                    const int weight = (2 - std::abs(dx)) * (2 - std::abs(dy));
                    total_weight += weight;
                    sum += weight * raw[index(x + dx, y + dy)];
                }
            }
            pixels[index(x, y)].smoothed = sum / total_weight;
        }
    }

    // Estimate local background and contrast from a surrounding annulus.
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            std::vector<double> ring;
            for (int dy = -5; dy <= 5; ++dy) {
                for (int dx = -5; dx <= 5; ++dx) {
                    const int radius_squared = dx * dx + dy * dy;
                    if (radius_squared >= 9 && radius_squared <= 25 && inside(x + dx, y + dy)) {
                        ring.push_back(pixels[index(x + dx, y + dy)].smoothed);
                    }
                }
            }
            Pixel& pixel = pixels[index(x, y)];
            pixel.background = median(ring);
            pixel.contrast = pixel.smoothed - pixel.background;
            for (double& neighbor : ring) neighbor = std::abs(neighbor - pixel.background);
            // The count-dependent floor prevents an almost flat ring from inflating the score.
            const double noise_floor = 0.1 + 0.05 * std::sqrt(std::max(0.0, pixel.background));
            pixel.score = pixel.contrast / std::max(noise_floor, 1.4826 * median(std::move(ring)));
        }
    }

    std::ofstream image(image_path);
    image.exceptions(std::ios::badbit | std::ios::failbit);
    image << "x_um,y_um,raw_kcps,smoothed_kcps,background_kcps,contrast_kcps,score\n" << std::setprecision(12);
    std::vector<int> peaks;
    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            const int current = index(x, y);
            const Pixel& pixel = pixels[current];
            image << x_axis[x] << ',' << y_axis[y] << ',' << raw[current] << ',' << pixel.smoothed << ','
                  << pixel.background << ',' << pixel.contrast << ',' << pixel.score << '\n';
            bool peak = pixel.contrast > 0;
            for (int dy = -1; peak && dy <= 1; ++dy) {
                for (int dx = -1; peak && dx <= 1; ++dx) {
                    if (!inside(x + dx, y + dy)) continue;
                    const int neighbor = index(x + dx, y + dy);
                    const double other = pixels[neighbor].contrast;
                    peak = other < pixel.contrast || (other == pixel.contrast && neighbor >= current);
                }
            }
            if (peak) peaks.push_back(current);
        }
    }
    image.close();
    std::stable_sort(peaks.begin(), peaks.end(), [&pixels](int a, int b) {
        return pixels[a].score > pixels[b].score;
    });
    std::cout << "rank,x_um,y_um,z_um,contrast_kcps,score\n" << std::setprecision(12);
    for (std::size_t rank = 0; rank < peaks.size(); ++rank) {
        const int i = peaks[rank];
        std::cout << rank + 1 << ',' << x_axis[i % width] << ',' << y_axis[i / width] << ','
                  << z << ',' << pixels[i].contrast << ',' << pixels[i].score << '\n';
    }
    if (!std::cout) throw std::runtime_error("Could not write candidate list");
    return 0;
}

int main(int argc, char** argv) {
    if (argc != 3) {
        std::cerr << "Usage: nv_candidates scan.csv enhanced.csv > candidates.csv\n";
        return 2;
    }
    try {
        return run(argv[1], argv[2]);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
