package com.nwafu.campusnet.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * 密码存储：Android Keystore + AES-GCM。
 *
 * 桌面版用的是 Windows DPAPI（用户级加密，密钥由系统托管）；Android 上对应物
 * 就是 Keystore——密钥生成后**永不离开 TEE/StrongBox**，App 只能请求它加解密，
 * 即使拿到 APK 和数据目录也解不出明文。
 *
 * 密文格式：Base64(IV[12] + ciphertext+tag)。
 */
class CredentialStore(context: Context) {

    private val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private fun getOrCreateKey(): SecretKey {
        val ks = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (ks.getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }

        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(
                KEY_ALIAS,
                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
            )
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return generator.generateKey()
    }

    /** 保存密码；空串等价于清除。 */
    fun savePassword(password: String?) {
        if (password.isNullOrEmpty()) {
            clear()
            return
        }
        try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey())
            val iv = cipher.iv
            val body = cipher.doFinal(password.toByteArray(Charsets.UTF_8))
            val packed = ByteArray(iv.size + body.size)
            System.arraycopy(iv, 0, packed, 0, iv.size)
            System.arraycopy(body, 0, packed, iv.size, body.size)
            prefs.edit().putString(KEY_CIPHERTEXT, Base64.encodeToString(packed, Base64.NO_WRAP)).apply()
        } catch (e: Exception) {
            // 加密失败就当作没存，避免把明文落到别处
            clear()
        }
    }

    /** 读取密码；密钥失效或数据损坏时返回 null 并清掉脏数据。 */
    fun loadPassword(): String? {
        val encoded = prefs.getString(KEY_CIPHERTEXT, null) ?: return null
        return try {
            val packed = Base64.decode(encoded, Base64.NO_WRAP)
            if (packed.size <= IV_SIZE) return null
            val iv = packed.copyOfRange(0, IV_SIZE)
            val body = packed.copyOfRange(IV_SIZE, packed.size)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), GCMParameterSpec(TAG_BITS, iv))
            String(cipher.doFinal(body), Charsets.UTF_8)
        } catch (e: Exception) {
            clear()
            null
        }
    }

    fun hasPassword(): Boolean = prefs.contains(KEY_CIPHERTEXT)

    fun clear() {
        prefs.edit().remove(KEY_CIPHERTEXT).apply()
    }

    private companion object {
        const val PREFS = "campusnet_secret"
        const val KEY_CIPHERTEXT = "password_ciphertext"
        const val KEY_ALIAS = "campusnet_password_key"
        const val ANDROID_KEYSTORE = "AndroidKeyStore"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
        const val IV_SIZE = 12
        const val TAG_BITS = 128
    }
}
