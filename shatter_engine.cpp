#include <iostream>
#include <fstream>
#include <vector>
#include <string>
#include <filesystem>
#include <zlib.h>
#include <openssl/evp.h>
#include <openssl/sha.h>
#include <openssl/rand.h>
#include <pwd.h>
#include <unistd.h>

namespace fs = std::filesystem;

// ─── GALOIS FIELD GF(2^8) MATH ───────────────────────────────────────
unsigned char gf_exp[512];
unsigned char gf_log[256];

void init_gf() {
    int x = 1;
    for (int i = 0; i < 255; i++) {
        gf_exp[i] = x;
        gf_log[x] = i;
        x <<= 1;
        if (x & 0x100) x ^= 0x11D; // Standard AES primitive polynomial
    }
    for (int i = 255; i < 512; i++) gf_exp[i] = gf_exp[i - 255];
}

unsigned char gf_mul(unsigned char a, unsigned char b) {
    if (a == 0 || b == 0) return 0;
    return gf_exp[gf_log[a] + gf_log[b]];
}

unsigned char gf_add(unsigned char a, unsigned char b) { return a ^ b; }

unsigned char eval_poly(const std::vector<unsigned char>& coeffs, unsigned char x) {
    unsigned char result = 0;
    unsigned char x_pow = 1;
    for (unsigned char c : coeffs) {
        if (c != 0) result = gf_add(result, gf_mul(c, x_pow));
        x_pow = gf_mul(x_pow, x);
    }
    return result;
}

unsigned char gf_inv(unsigned char a) {
    if (a == 0) return 0;
    return gf_exp[255 - gf_log[a]];
}

void gf_invert_matrix(std::vector<std::vector<unsigned char>>& matrix, int K) {
    std::vector<std::vector<unsigned char>> inv(K, std::vector<unsigned char>(K, 0));
    for (int i = 0; i < K; i++) inv[i][i] = 1;

    for (int i = 0; i < K; i++) {
        if (matrix[i][i] == 0) {
            for (int r = i + 1; r < K; r++) {
                if (matrix[r][i] != 0) {
                    std::swap(matrix[i], matrix[r]);
                    std::swap(inv[i], inv[r]);
                    break;
                }
            }
        }
        unsigned char pivot = matrix[i][i];
        if (pivot == 0) throw std::runtime_error("Mathematical anomaly: Singular Galois matrix. Cannot rebuild.");

        unsigned char pivot_inv = gf_inv(pivot);
        for (int j = 0; j < K; j++) {
            matrix[i][j] = gf_mul(matrix[i][j], pivot_inv);
            inv[i][j] = gf_mul(inv[i][j], pivot_inv);
        }

        for (int r = 0; r < K; r++) {
            if (r != i) {
                unsigned char factor = matrix[r][i];
                for (int j = 0; j < K; j++) {
                    matrix[r][j] = gf_add(matrix[r][j], gf_mul(factor, matrix[i][j]));
                    inv[r][j] = gf_add(inv[r][j], gf_mul(factor, inv[i][j]));
                }
            }
        }
    }
    matrix = inv;
}

// ─── HARDWARE ENTANGLED POINTS ───────────────────────────────────────
std::vector<unsigned char> generate_entangled_points(const std::vector<unsigned char>& master_key, int N) {
    std::vector<unsigned char> points;
    bool used[256] = {false};
    used[0] = true; // x=0 is invalid for evaluation points
    for(unsigned char b : master_key) {
        if (!used[b]) {
            points.push_back(b);
            used[b] = true;
            if (points.size() == N) break;
        }
    }
    unsigned char fallback = 1;
    while(int(points.size()) < N) {
        if (!used[fallback]) {
            points.push_back(fallback);
            used[fallback] = true;
        }
        fallback++;
    }
    return points;
}

// ─── ENGINE ──────────────────────────────────────────────────────────
std::vector<unsigned char> derive_key(const std::string& salt) {
    std::vector<unsigned char> hash(SHA256_DIGEST_LENGTH);
    SHA256(reinterpret_cast<const unsigned char*>(salt.data()), salt.size(), hash.data());
    return hash;
}

std::vector<unsigned char> encrypt_aes(const std::vector<unsigned char>& plain, const std::vector<unsigned char>& key) {
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    std::vector<unsigned char> cipher(plain.size() + EVP_MAX_BLOCK_LENGTH + 16);
    int len, ciphertext_len;
    unsigned char iv[16];

    if (RAND_bytes(iv, 16) != 1) {
        EVP_CIPHER_CTX_free(ctx);
        throw std::runtime_error("IV generation failed");
    }

    std::copy(iv, iv + 16, cipher.begin());

    EVP_EncryptInit_ex(ctx, EVP_aes_256_cbc(), NULL, key.data(), iv);
    EVP_EncryptUpdate(ctx, cipher.data() + 16, &len, plain.data(), plain.size());
    ciphertext_len = len + 16;
    EVP_EncryptFinal_ex(ctx, cipher.data() + 16 + len, &len);
    ciphertext_len += len;

    EVP_CIPHER_CTX_free(ctx);
    cipher.resize(ciphertext_len);
    return cipher;
}

std::vector<unsigned char> decrypt_aes(const std::vector<unsigned char>& cipher, const std::vector<unsigned char>& key) {
    if (cipher.size() < 16) throw std::runtime_error("Ciphertext too small");
    std::vector<unsigned char> plain(cipher.size());
    int len, plaintext_len;
    
    EVP_CIPHER_CTX *ctx = EVP_CIPHER_CTX_new();
    EVP_DecryptInit_ex(ctx, EVP_aes_256_cbc(), NULL, key.data(), cipher.data()); // First 16 bytes is IV
    EVP_DecryptUpdate(ctx, plain.data(), &len, cipher.data() + 16, cipher.size() - 16);
    plaintext_len = len;
    
    if (EVP_DecryptFinal_ex(ctx, plain.data() + len, &len) != 1) {
        EVP_CIPHER_CTX_free(ctx);
        throw std::runtime_error("AES Decryption Failed. Invalid Key or Corruption.");
    }
    plaintext_len += len;
    EVP_CIPHER_CTX_free(ctx);
    plain.resize(plaintext_len);
    return plain;
}

std::string get_secure_shard_dir() {
    struct passwd *pw = getpwuid(getuid());
    return std::string(pw->pw_dir) + "/.ansx_vault/shards";
}

extern "C" {
    int run_shatter_engine(const char* input_path, const char* nfc_key) {
        try {
            std::string inputPath(input_path);
            std::string nfcKey(nfc_key);
            
            std::ifstream file(inputPath, std::ios::binary | std::ios::ate);
            if (!file.is_open()) return -1;
            std::streamsize size = file.tellg();
            file.seekg(0, std::ios::beg);
            
            std::vector<unsigned char> raw_buffer(size);
            if (!file.read((char*)raw_buffer.data(), size)) return -1;
            file.close();

            uLongf comp_size = compressBound(size);
            std::vector<unsigned char> comp_buf(comp_size);
            if (compress(comp_buf.data(), &comp_size, raw_buffer.data(), size) != Z_OK) return -2;
            comp_buf.resize(comp_size);

            auto master_key = derive_key(nfcKey);
            std::vector<unsigned char> encrypted_data;
            try { encrypted_data = encrypt_aes(comp_buf, master_key); } 
            catch (...) { return -3; }

            std::string shard_dir = get_secure_shard_dir();
            if (!fs::exists(shard_dir)) {
                fs::create_directories(shard_dir);
                fs::permissions(shard_dir, fs::perms::owner_all, fs::perm_options::replace);
            }
            
            // ─── REED-SOLOMON HARDWARE ENTANGLED ENCODING ───
            int K_DATA = 8;
            int N_SHARDS = 12;

            // Pad the encrypted data block to a multiple of K_DATA
            while (encrypted_data.size() % K_DATA != 0) {
                encrypted_data.push_back(0);
            }
            size_t chunk_count = encrypted_data.size() / K_DATA;

            // Prepare shard buffers
            std::vector<std::vector<unsigned char>> shards(N_SHARDS, std::vector<unsigned char>(chunk_count));

            init_gf();
            // The magic happens here: X-Coordinates are defined by NFC/GPS key
            auto eval_points = generate_entangled_points(master_key, N_SHARDS);

            for (size_t chunk = 0; chunk < chunk_count; ++chunk) {
                std::vector<unsigned char> polynomial(K_DATA);
                for (int k = 0; k < K_DATA; ++k) {
                    polynomial[k] = encrypted_data[chunk * K_DATA + k];
                }
                
                for (int n = 0; n < N_SHARDS; ++n) {
                    shards[n][chunk] = eval_poly(polynomial, eval_points[n]);
                }
            }

            // Write Shards
            for (int i = 0; i < N_SHARDS; ++i) {
                std::string target_path = shard_dir + "/fragment_" + std::to_string(i+1) + ".ansx";
                std::ofstream shard_file(target_path, std::ios::binary);
                if (!shard_file.is_open()) return -4;
                shard_file.write((char*)shards[i].data(), shards[i].size());
            }
            
            return 0;
        } catch (...) { return -99; }
    }

    int unshatter_engine(const char* shard_dir_path, const char* out_file_path, const char* nfc_key) {
        try {
            std::string shardDir(shard_dir_path);
            std::string outFile(out_file_path);
            std::string nfcKey(nfc_key);

            auto master_key = derive_key(nfcKey);
            init_gf();
            
            int K_DATA = 8;
            int N_SHARDS = 12;
            auto eval_points = generate_entangled_points(master_key, N_SHARDS);

            std::vector<int> surviving_indices;
            std::vector<std::vector<unsigned char>> surviving_shards;

            for (int i = 0; i < N_SHARDS; i++) {
                std::string current_shard = shardDir + "/fragment_" + std::to_string(i+1) + ".ansx";
                if (fs::exists(current_shard)) {
                    std::ifstream file(current_shard, std::ios::binary | std::ios::ate);
                    if (file.is_open()) {
                        std::streamsize sz = file.tellg();
                        file.seekg(0, std::ios::beg);
                        std::vector<unsigned char> buf(sz);
                        file.read((char*)buf.data(), sz);
                        surviving_shards.push_back(buf);
                        surviving_indices.push_back(i);
                    }
                }
                if (surviving_shards.size() == K_DATA) break; // We only need K shards
            }

            if (surviving_shards.size() < K_DATA) return -10; // Not enough shards

            size_t chunk_count = surviving_shards[0].size();
            std::vector<std::vector<unsigned char>> matrix(K_DATA, std::vector<unsigned char>(K_DATA));
            for (int i = 0; i < K_DATA; i++) {
                unsigned char x = eval_points[surviving_indices[i]];
                unsigned char x_pow = 1;
                for (int j = 0; j < K_DATA; j++) {
                    matrix[i][j] = x_pow;
                    x_pow = gf_mul(x_pow, x);
                }
            }

            gf_invert_matrix(matrix, K_DATA);

            std::vector<unsigned char> encrypted_data(chunk_count * K_DATA);
            for (size_t chunk = 0; chunk < chunk_count; chunk++) {
                std::vector<unsigned char> y(K_DATA);
                for (int i = 0; i < K_DATA; i++) y[i] = surviving_shards[i][chunk];

                for (int row = 0; row < K_DATA; row++) {
                    unsigned char val = 0;
                    for (int col = 0; col < K_DATA; col++) {
                        val = gf_add(val, gf_mul(matrix[row][col], y[col]));
                    }
                    encrypted_data[chunk * K_DATA + row] = val;
                }
            }

            // Trim AES padding logic is handled internally, but let's decrypt
            std::vector<unsigned char> comp_buf;
            try { comp_buf = decrypt_aes(encrypted_data, master_key); }
            catch (...) { return -11; }

            // Decompress
            uLongf uncomp_size = comp_buf.size() * 10; // Guessed max ratio
            std::vector<unsigned char> raw_buf(uncomp_size);
            int res = uncompress(raw_buf.data(), &uncomp_size, comp_buf.data(), comp_buf.size());
            while (res == Z_BUF_ERROR) {
                uncomp_size *= 2;
                raw_buf.resize(uncomp_size);
                res = uncompress(raw_buf.data(), &uncomp_size, comp_buf.data(), comp_buf.size());
            }
            if (res != Z_OK) return -12;
            raw_buf.resize(uncomp_size);

            std::ofstream out(outFile, std::ios::binary);
            if (!out.is_open()) return -13;
            out.write((char*)raw_buf.data(), raw_buf.size());

            return 0;
        } catch (...) { return -99; }
    }
}